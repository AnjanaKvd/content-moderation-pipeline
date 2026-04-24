import os
import time
import hashlib
import uuid
import logging
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware

from schemas.moderation import (
    ModerationRequest,
    ModerationResponse,
    ModerationResult,
    BatchModerationRequest,
    BatchModerationResponse,
    HealthResponse,
)
from models.classifier import get_classifier
from services.cache import get_cache
from services.queue import get_queue
from services.telemetry import setup_telemetry, track_moderation_event

logger = logging.getLogger(__name__)

app_start_time = time.time()


def normalize_comment(text: str) -> str:
    text = text.lower().strip()
    return re.sub(r"\s+", " ", text)


def hash_comment(normalized: str) -> str:
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ON STARTUP
    logger.info("Starting up Content Moderation API...")
    try:
        classifier = get_classifier()
        logger.info(f"Classifier loaded in {classifier.load_time_ms:.2f} ms")
    except Exception as e:
        logger.error(f"Failed to load classifier: {e}")

    # Phase 2 - Attempt Redis connection
    cache = get_cache()
    if await cache.ping():
        logger.info("Connected to Redis cache.")
    else:
        logger.warning("Redis cache unavailable or not configured.")

    # Phase 3 - Attempt Service Bus connection
    queue = get_queue()
    if type(queue).__name__ != "NullQueue":
        logger.info("Connected to Service Bus.")
    else:
        logger.warning("Service Bus unavailable or not configured.")

    # Phase 3 - Setup Telemetry
    app_insights_conn_str = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if app_insights_conn_str:
        try:
            setup_telemetry(app_insights_conn_str)
            logger.info("Application Insights telemetry configured.")
        except Exception as e:
            logger.warning(f"Failed to initialize telemetry: {e}")
    else:
        logger.info(
            "APPLICATIONINSIGHTS_CONNECTION_STRING not set, telemetry disabled."
        )

    # --- THE CRITICAL FIX ---
    # This must be at the base indentation level of the function
    yield

    # ON SHUTDOWN
    logger.info("Shutting down...")
    # Phase 2 - Close Redis connection
    await cache.close()
    # Phase 3 - Close Service Bus connection
    await queue.close()


app = FastAPI(
    title="Content Moderation API",
    version="1.0.0",
    description="API for detecting toxicity and hate speech in text",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = (time.time() - start_time) * 1000
    response.headers["X-Process-Time-Ms"] = str(round(process_time, 2))
    return response


@app.get("/")
async def root():
    return RedirectResponse(url="/docs")


@app.get("/health", response_model=HealthResponse)
async def health_check():
    classifier = None
    try:
        classifier = get_classifier()
        model_loaded = True
        model_load_time_ms = classifier.load_time_ms
    except Exception:
        model_loaded = False
        model_load_time_ms = 0.0

    cache = get_cache()
    redis_connected = await cache.ping()

    queue = get_queue()
    servicebus_connected = type(queue).__name__ != "NullQueue"

    status = "unhealthy"
    if model_loaded and redis_connected:
        status = "healthy"
    elif model_loaded:
        status = "degraded"

    uptime = time.time() - app_start_time

    return HealthResponse(
        status=status,
        model_loaded=model_loaded,
        redis_connected=redis_connected,
        servicebus_connected=servicebus_connected,
        model_load_time_ms=model_load_time_ms,
        uptime_seconds=uptime,
    )


@app.post(
    "/moderate",
    response_model=ModerationResponse,
    description="Classify a single comment for toxicity and hate speech",
)
async def moderate(request: ModerationRequest):
    normalized = normalize_comment(request.comment)
    comment_hash = hash_comment(normalized)

    # Phase 2 - Check Redis cache
    cache = get_cache()
    cached_result = await cache.get(comment_hash)
    if cached_result is not None:
        cached_result["cached"] = True
        cached_result["comment_hash"] = comment_hash
        logger.info(f"Cache hit for hash {comment_hash[:8]}...")

        # Phase 3 - Track metrics
        platform = request.platform if request.platform else "unknown"
        track_moderation_event(cached_result, cached=True, platform=platform)

        return ModerationResponse(
            request_id=str(uuid.uuid4()),
            result=ModerationResult(**cached_result),
            processed_at=datetime.now(timezone.utc),
        )

    classifier = get_classifier()
    try:
        result_dict = classifier.predict(request.comment)
    except Exception as e:
        logger.error(f"Error during prediction: {e}")
        raise HTTPException(status_code=500, detail="Inference failed")

    # Phase 2 - Store in Redis cache
    await cache.set(comment_hash, result_dict)

    # Phase 3 - Track metrics in App Insights
    platform = request.platform if request.platform else "unknown"
    track_moderation_event(result_dict, cached=False, platform=platform)

    result = ModerationResult(
        label=result_dict["label"],
        confidence=result_dict["confidence"],
        scores=result_dict["scores"],
        inference_time_ms=result_dict["inference_time_ms"],
        cached=False,
        comment_hash=comment_hash,
    )

    return ModerationResponse(
        request_id=str(uuid.uuid4()),
        result=result,
        processed_at=datetime.now(timezone.utc),
    )


@app.post(
    "/moderate/batch",
    response_model=BatchModerationResponse,
    description="In production, dumps to Service Bus queue and returns immediately",
)
async def moderate_batch(request: BatchModerationRequest):
    job_id = str(uuid.uuid4())

    # Phase 3 - Publish to Service Bus queue
    comments_as_dicts = [
        {
            "comment": c.comment,
            "comment_hash": hash_comment(normalize_comment(c.comment)),
            "platform": c.platform,
        }
        for c in request.comments
    ]

    queue = get_queue()
    published = await queue.publish_batch(job_id, comments_as_dicts)
    queue_depth = await queue.get_queue_depth()

    estimated_completion = (
        max(5, (queue_depth // 32) * 2)
        if queue_depth > 0
        else max(5, (published // 32) * 2)
    )

    return BatchModerationResponse(
        job_id=job_id,
        queued_count=published,
        status="queued",
        estimated_completion_seconds=estimated_completion,
        queue_position=queue_depth if queue_depth >= 0 else None,
    )

from pydantic import BaseModel, Field
from typing import Literal, Optional, List, Dict
from datetime import datetime
import uuid

class ModerationRequest(BaseModel):
    comment: str = Field(..., min_length=1, max_length=5000)
    user_id: Optional[str] = None
    platform: Optional[str] = None

class ModerationResult(BaseModel):
    label: Literal["toxic", "non_toxic"]
    confidence: float
    scores: Dict[str, float]
    inference_time_ms: float
    cached: bool = False
    comment_hash: str

class ModerationResponse(BaseModel):
    request_id: str
    result: ModerationResult
    processed_at: datetime
    api_version: str = "1.0.0"

class BatchModerationRequest(BaseModel):
    comments: List[ModerationRequest] = Field(..., min_length=1, max_length=1000)
    callback_url: Optional[str] = None

class BatchModerationResponse(BaseModel):
    job_id: str
    queued_count: int
    status: Literal["queued", "processing", "completed", "failed"]
    estimated_completion_seconds: int
    queue_position: Optional[int] = None

class HealthResponse(BaseModel):
    model_config = {"protected_namespaces": ()}
    status: Literal["healthy", "degraded", "unhealthy"]
    model_loaded: bool
    redis_connected: bool
    servicebus_connected: bool
    model_load_time_ms: float
    uptime_seconds: float

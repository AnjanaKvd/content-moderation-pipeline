import os
import time
import json
import logging
import signal
import asyncio
import httpx
from azure.servicebus.aio import ServiceBusClient

from models.classifier import get_classifier
from services.cache import get_cache

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Control flag for graceful shutdown
shutdown_event = asyncio.Event()

def handle_sigterm(*args):
    logger.info("Worker shutting down gracefully (SIGTERM received)")
    shutdown_event.set()

signal.signal(signal.SIGINT, handle_sigterm)
signal.signal(signal.SIGTERM, handle_sigterm)

async def process_batch(messages, receiver, classifier, cache):
    if not messages:
        return
        
    start_time = time.time()
    
    uncached_texts = []
    uncached_indices = []
    
    cache_hits = 0
    results_by_job = {} # To aggregate if needed
    
    # Pre-process messages
    for idx, msg in enumerate(messages):
        try:
            body = json.loads(str(msg))
            comment_hash = body.get("comment_hash")
            comment_text = body.get("comment_text")
            
            # Check cache
            cached = await cache.get(comment_hash)
            if cached is not None:
                cache_hits += 1
                await receiver.complete_message(msg)
            else:
                uncached_texts.append(comment_text)
                uncached_indices.append(idx)
        except Exception as e:
            logger.error(f"Failed to process message {msg.message_id}: {e}")
            if msg.delivery_count >= 3:
                await receiver.dead_letter_message(msg, reason="ProcessingError", error_description=str(e))
            else:
                await receiver.abandon_message(msg)
                
    # Run inference for uncached
    if uncached_texts:
        try:
            inference_results = classifier.predict_batch(uncached_texts)
            
            for i, result_dict in enumerate(inference_results):
                orig_idx = uncached_indices[i]
                msg = messages[orig_idx]
                body = json.loads(str(msg))
                comment_hash = body.get("comment_hash")
                
                await cache.set(comment_hash, result_dict)
                await receiver.complete_message(msg)
                
        except Exception as e:
            logger.error(f"Inference failed for batch: {e}")
            for orig_idx in uncached_indices:
                msg = messages[orig_idx]
                if msg.delivery_count >= 3:
                    await receiver.dead_letter_message(msg, reason="InferenceError", error_description=str(e))
                else:
                    await receiver.abandon_message(msg)

    elapsed_ms = (time.time() - start_time) * 1000
    logger.info(f"Processed {len(messages)} messages ({cache_hits} cache hits) in {elapsed_ms:.2f}ms")

async def worker_loop():
    conn_str = os.environ.get("SERVICEBUS_CONNECTION_STRING")
    queue_name = os.environ.get("SERVICEBUS_QUEUE_NAME", "moderation-queue")
    batch_size = int(os.environ.get("INFERENCE_BATCH_SIZE", "32"))

    if not conn_str:
        logger.error("SERVICEBUS_CONNECTION_STRING is not set. Worker cannot start.")
        return

    logger.info("Initializing worker components...")
    classifier = get_classifier()
    cache = get_cache()
    
    async with ServiceBusClient.from_connection_string(conn_str) as client:
        async with client.get_queue_receiver(queue_name=queue_name, max_wait_time=5) as receiver:
            logger.info("Worker started listening to queue.")
            
            while not shutdown_event.is_set():
                try:
                    messages = await receiver.receive_messages(
                        max_message_count=batch_size,
                        max_wait_time=5
                    )
                    
                    if messages:
                        await process_batch(messages, receiver, classifier, cache)
                except Exception as e:
                    logger.error(f"Error in worker loop: {e}")
                    await asyncio.sleep(1)

    logger.info("Worker stopped.")

if __name__ == "__main__":
    asyncio.run(worker_loop())

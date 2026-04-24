import os
import logging
from opentelemetry import metrics
from azure.monitor.opentelemetry import configure_azure_monitor

logger = logging.getLogger(__name__)

# Global meters and instruments
_meter = None
_req_counter = None
_inf_histogram = None
_conf_histogram = None
_cache_counter = None

def setup_telemetry(connection_string: str):
    global _meter, _req_counter, _inf_histogram, _conf_histogram, _cache_counter
    
    try:
        configure_azure_monitor(connection_string=connection_string)
        
        _meter = metrics.get_meter("content_moderation_api")
        
        _req_counter = _meter.create_counter(
            "moderation_requests_total",
            description="Total number of moderation requests"
        )
        
        _inf_histogram = _meter.create_histogram(
            "moderation_inference_ms",
            description="Inference latency distribution in ms",
            unit="ms"
        )
        
        _conf_histogram = _meter.create_histogram(
            "moderation_confidence",
            description="Distribution of confidence scores"
        )
        
        _cache_counter = _meter.create_counter(
            "cache_operations_total",
            description="Total number of cache operations"
        )
        
        logger.info("Application Insights telemetry configured successfully.")
    except Exception as e:
        logger.error(f"Failed to setup telemetry: {e}")

def track_moderation_event(result: dict, cached: bool, platform: str = "unknown"):
    if not _meter:
        return
        
    try:
        label = result.get("label", "unknown")
        confidence = result.get("confidence", 0.0)
        inference_time_ms = result.get("inference_time_ms", 0.0)
        
        _req_counter.add(1, {"label": label, "cached": cached, "platform": platform})
        
        if not cached:
            _inf_histogram.record(inference_time_ms, {"label": label})
            
        _conf_histogram.record(confidence, {"label": label})
        
    except Exception as e:
        logger.warning(f"Failed to track moderation event: {e}")

def track_cache_operation(operation: str):
    if not _meter:
        return
        
    try:
        _cache_counter.add(1, {"operation": operation})
    except Exception as e:
        logger.warning(f"Failed to track cache operation: {e}")

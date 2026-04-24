import json
import logging
import os
from typing import Optional, Dict, Any
import redis.asyncio as redis
from services.telemetry import track_cache_operation

logger = logging.getLogger(__name__)

class NullCache:
    """Fallback cache for development when Redis is not available."""
    def __init__(self):
        logger.info("Redis not configured, caching disabled")
        self._stats = {"hits": 0, "misses": 0}

    async def get(self, comment_hash: str) -> Optional[Dict[str, Any]]:
        self._stats["misses"] += 1
        return None

    async def set(self, comment_hash: str, result: Dict[str, Any]) -> bool:
        return False

    async def ping(self) -> bool:
        return False

    async def invalidate(self, comment_hash: str) -> bool:
        return False

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            "hits": self._stats["hits"],
            "misses": self._stats["misses"],
            "hit_rate": 0.0
        }

    async def close(self):
        pass


class ModerationCache:
    def __init__(self, host: str, port: int, password: str, ssl: bool, ttl: int):
        self.redis = redis.Redis(
            host=host,
            port=port,
            password=password,
            ssl=ssl,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            retry_on_timeout=True
        )
        self.ttl = ttl
        self._stats = {"hits": 0, "misses": 0}

    async def get(self, comment_hash: str) -> Optional[Dict[str, Any]]:
        key = f"moderation:v1:{comment_hash}"
        try:
            result = await self.redis.get(key)
            if result:
                self._stats["hits"] += 1
                track_cache_operation("hit")
                return json.loads(result)
            self._stats["misses"] += 1
            track_cache_operation("miss")
            return None
        except Exception as e:
            logger.warning(f"Cache get failed for {key}: {e}")
            self._stats["misses"] += 1
            track_cache_operation("miss_error")
            return None

    async def set(self, comment_hash: str, result: Dict[str, Any]) -> bool:
        key = f"moderation:v1:{comment_hash}"
        try:
            serialized_result = json.dumps(result)
            await self.redis.setex(key, self.ttl, serialized_result)
            track_cache_operation("set")
            return True
        except Exception as e:
            logger.warning(f"Cache set failed for {key}: {e}")
            track_cache_operation("set_error")
            return False

    async def ping(self) -> bool:
        try:
            return await self.redis.ping()
        except Exception:
            return False

    async def invalidate(self, comment_hash: str) -> bool:
        key = f"moderation:v1:{comment_hash}"
        try:
            deleted = await self.redis.delete(key)
            return deleted > 0
        except Exception as e:
            logger.warning(f"Cache invalidate failed for {key}: {e}")
            return False

    @property
    def stats(self) -> Dict[str, Any]:
        total = self._stats["hits"] + self._stats["misses"]
        hit_rate = self._stats["hits"] / total if total > 0 else 0.0
        return {
            "hits": self._stats["hits"],
            "misses": self._stats["misses"],
            "hit_rate": hit_rate
        }

    async def close(self):
        await self.redis.close()

_cache = None

def get_cache() -> Any:
    global _cache
    if _cache is None:
        redis_host = os.getenv("REDIS_HOST")
        if not redis_host:
            _cache = NullCache()
        else:
            port_str = os.getenv("REDIS_PORT", "6379")
            port = int(port_str) if port_str.isdigit() else 6379
            password = os.getenv("REDIS_PASSWORD", "")
            ssl = os.getenv("REDIS_SSL", "false").lower() == "true"
            ttl_str = os.getenv("REDIS_CACHE_TTL", "86400")
            ttl = int(ttl_str) if ttl_str.isdigit() else 86400
            
            _cache = ModerationCache(
                host=redis_host,
                port=port,
                password=password,
                ssl=ssl,
                ttl=ttl
            )
    return _cache

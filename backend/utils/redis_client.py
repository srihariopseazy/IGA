import json
import logging
from typing import Optional, Any

import redis.asyncio as aioredis
from backend.config import settings

logger = logging.getLogger(__name__)

_FAILED_LOGIN_PREFIX = "failed_logins:"
_TOKEN_BLACKLIST_PREFIX = "blacklist:jti:"
_USER_CACHE_PREFIX = "user_cache:"


class RedisClient:
    """Async Redis client wrapper with helpers for IGA operations."""

    def __init__(self) -> None:
        self._client: Optional[aioredis.Redis] = None

    def _get_client(self) -> aioredis.Redis:
        if self._client is None:
            self._client = aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
            )
        return self._client

    async def get(self, key: str) -> Optional[str]:
        try:
            return await self._get_client().get(key)
        except Exception as exc:
            logger.error("Redis GET error for key %s: %s", key, exc)
            return None

    async def set(self, key: str, value: Any, expire: Optional[int] = None) -> bool:
        try:
            serialized = json.dumps(value) if not isinstance(value, str) else value
            if expire:
                await self._get_client().setex(key, expire, serialized)
            else:
                await self._get_client().set(key, serialized)
            return True
        except Exception as exc:
            logger.error("Redis SET error for key %s: %s", key, exc)
            return False

    async def delete(self, key: str) -> int:
        try:
            return await self._get_client().delete(key)
        except Exception as exc:
            logger.error("Redis DELETE error for key %s: %s", key, exc)
            return 0

    async def exists(self, key: str) -> bool:
        try:
            result = await self._get_client().exists(key)
            return bool(result)
        except Exception as exc:
            logger.error("Redis EXISTS error for key %s: %s", key, exc)
            return False

    async def incr(self, key: str) -> int:
        try:
            return await self._get_client().incr(key)
        except Exception as exc:
            logger.error("Redis INCR error for key %s: %s", key, exc)
            return 0

    async def expire(self, key: str, seconds: int) -> bool:
        try:
            return await self._get_client().expire(key, seconds)
        except Exception as exc:
            logger.error("Redis EXPIRE error for key %s: %s", key, exc)
            return False

    async def ttl(self, key: str) -> int:
        try:
            return await self._get_client().ttl(key)
        except Exception as exc:
            logger.error("Redis TTL error for key %s: %s", key, exc)
            return -1

    async def hset(self, name: str, mapping: dict) -> int:
        try:
            return await self._get_client().hset(name, mapping=mapping)
        except Exception as exc:
            logger.error("Redis HSET error for %s: %s", name, exc)
            return 0

    async def hget(self, name: str, key: str) -> Optional[str]:
        try:
            return await self._get_client().hget(name, key)
        except Exception as exc:
            logger.error("Redis HGET error for %s %s: %s", name, key, exc)
            return None

    async def hgetall(self, name: str) -> dict:
        try:
            return await self._get_client().hgetall(name) or {}
        except Exception as exc:
            logger.error("Redis HGETALL error for %s: %s", name, exc)
            return {}

    async def lpush(self, key: str, *values) -> int:
        try:
            serialized = [json.dumps(v) if not isinstance(v, str) else v for v in values]
            return await self._get_client().lpush(key, *serialized)
        except Exception as exc:
            logger.error("Redis LPUSH error for key %s: %s", key, exc)
            return 0

    async def lrange(self, key: str, start: int, stop: int) -> list:
        try:
            return await self._get_client().lrange(key, start, stop) or []
        except Exception as exc:
            logger.error("Redis LRANGE error for key %s: %s", key, exc)
            return []

    async def sadd(self, key: str, *values) -> int:
        try:
            return await self._get_client().sadd(key, *values)
        except Exception as exc:
            logger.error("Redis SADD error for key %s: %s", key, exc)
            return 0

    async def smembers(self, key: str) -> set:
        try:
            return await self._get_client().smembers(key) or set()
        except Exception as exc:
            logger.error("Redis SMEMBERS error for key %s: %s", key, exc)
            return set()

    async def publish(self, channel: str, message: Any) -> int:
        try:
            serialized = json.dumps(message) if not isinstance(message, str) else message
            return await self._get_client().publish(channel, serialized)
        except Exception as exc:
            logger.error("Redis PUBLISH error for channel %s: %s", channel, exc)
            return 0

    # --- Token blacklist ---

    async def blacklist_token(self, jti: str, expire_seconds: int) -> bool:
        """Add a JTI to the token blacklist with expiry matching token TTL."""
        key = f"{_TOKEN_BLACKLIST_PREFIX}{jti}"
        return await self.set(key, "1", expire=expire_seconds)

    async def is_token_blacklisted(self, jti: str) -> bool:
        """Check if a JTI has been blacklisted (logged out)."""
        key = f"{_TOKEN_BLACKLIST_PREFIX}{jti}"
        return await self.exists(key)

    # --- User cache ---

    async def cache_user(
        self,
        user_id: str,
        user_data: dict,
        expire: int = 300,
    ) -> bool:
        """Cache user data for fast lookup (default 5 minutes)."""
        key = f"{_USER_CACHE_PREFIX}{user_id}"
        return await self.set(key, json.dumps(user_data), expire=expire)

    async def get_cached_user(self, user_id: str) -> Optional[dict]:
        """Retrieve cached user data. Returns None if not cached."""
        key = f"{_USER_CACHE_PREFIX}{user_id}"
        raw = await self.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    async def invalidate_user_cache(self, user_id: str) -> bool:
        """Remove user from cache (call on update/delete)."""
        key = f"{_USER_CACHE_PREFIX}{user_id}"
        return bool(await self.delete(key))

    # --- Failed login tracking ---

    async def track_failed_login(self, user_id: str) -> int:
        """Increment failed login counter. Returns new count."""
        key = f"{_FAILED_LOGIN_PREFIX}{user_id}"
        count = await self.incr(key)
        # Set expiry on first failure
        if count == 1:
            await self.expire(key, settings.LOCKOUT_DURATION_MINUTES * 60)
        return count

    async def clear_failed_logins(self, user_id: str) -> bool:
        """Clear failed login counter after successful login."""
        key = f"{_FAILED_LOGIN_PREFIX}{user_id}"
        return bool(await self.delete(key))

    async def get_failed_logins(self, user_id: str) -> int:
        """Get current failed login count."""
        key = f"{_FAILED_LOGIN_PREFIX}{user_id}"
        raw = await self.get(key)
        if raw is None:
            return 0
        try:
            return int(raw)
        except (ValueError, TypeError):
            return 0

    async def close(self) -> None:
        """Close the Redis connection pool."""
        if self._client:
            await self._client.aclose()
            self._client = None


redis_client = RedisClient()


async def get_redis_client() -> RedisClient:
    """Dependency / helper to retrieve the global RedisClient instance."""
    return redis_client

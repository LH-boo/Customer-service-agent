"""Redis 缓存：FAQ 答案、会话上下文、工单状态；Redis 不可用时自动降级为进程内缓存。"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

PREFIX = "hospital:"


class CacheService:
    def __init__(self) -> None:
        self._redis = None
        self._memory: dict[str, tuple[str, float]] = {}
        self.backend = "memory"

    async def connect(self) -> None:
        if not settings.redis_enabled:
            logger.info("Redis 已关闭，使用进程内缓存")
            return
        try:
            import redis.asyncio as aioredis

            client = aioredis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
            await client.ping()
            self._redis = client
            self.backend = "redis"
            logger.info("Redis 已连接: %s", settings.redis_url)
        except Exception as exc:  # 演示环境允许无 Redis 启动
            self.backend = "memory"
            logger.warning("Redis 连接失败，降级为进程内缓存: %s", exc)

    async def aclose(self) -> None:
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:
                pass
            self._redis = None

    async def get(self, key: str) -> Optional[str]:
        key = PREFIX + key
        if self._redis is not None:
            try:
                return await self._redis.get(key)
            except Exception as exc:
                logger.warning("Redis GET 失败，降级内存缓存: %s", exc)
        item = self._memory.get(key)
        if not item:
            return None
        value, expire_at = item
        if time.monotonic() > expire_at:
            self._memory.pop(key, None)
            return None
        return value

    async def set(self, key: str, value: str, ttl: int) -> None:
        key = PREFIX + key
        if self._redis is not None:
            try:
                await self._redis.set(key, value, ex=ttl)
                return
            except Exception as exc:
                logger.warning("Redis SET 失败，降级内存缓存: %s", exc)
        self._memory[key] = (value, time.monotonic() + ttl)

    async def delete(self, key: str) -> None:
        key = PREFIX + key
        if self._redis is not None:
            try:
                await self._redis.delete(key)
            except Exception:
                pass
        self._memory.pop(key, None)

    async def get_json(self, key: str) -> Any | None:
        raw = await self.get(key)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    async def set_json(self, key: str, value: Any, ttl: int) -> None:
        await self.set(key, json.dumps(value, ensure_ascii=False, default=str), ttl)

    # ---------- 会话上下文 ----------
    async def append_session_message(
        self, patient_id: int, session_id: str, role: str, content: str, intent: str | None = None
    ) -> None:
        key = f"chat:{patient_id}:{session_id}"
        history = await self.get_json(key) or []
        history.append({"role": role, "content": content, "intent": intent})
        await self.set_json(key, history[-20:], settings.session_ttl)

    async def get_session_history(self, patient_id: int, session_id: str) -> list[dict]:
        return await self.get_json(f"chat:{patient_id}:{session_id}") or []

    # ---------- FAQ 缓存 ----------
    @staticmethod
    def faq_key(question: str) -> str:
        normalized = "".join(question.split()).lower()
        return "faq:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]

    async def get_faq(self, question: str) -> dict | None:
        return await self.get_json(self.faq_key(question))

    async def set_faq(self, question: str, payload: dict) -> None:
        await self.set_json(self.faq_key(question), payload, settings.faq_cache_ttl)

    # ---------- 工单状态缓存 ----------
    @staticmethod
    def ticket_key(patient_id: int, ticket_no: str) -> str:
        return f"ticket:{patient_id}:{ticket_no}"

    async def invalidate_ticket(self, patient_id: int, ticket_no: str) -> None:
        await self.delete(self.ticket_key(patient_id, ticket_no))


cache = CacheService()

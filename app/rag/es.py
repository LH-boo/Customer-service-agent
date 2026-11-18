"""Elasticsearch 关键词检索（可选）：通过 REST 接口调用，不额外引入 SDK。"""
from __future__ import annotations

import logging
from typing import List

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class ESStore:
    def __init__(self) -> None:
        self.enabled = bool(settings.es_url)
        self.url = settings.es_url.rstrip("/")
        self.auth = (
            (settings.es_username, settings.es_password) if settings.es_username else None
        )

    async def search(self, query: str, top_k: int = 12) -> List[tuple[str, float]]:
        if not self.enabled:
            return []
        body = {
            "size": top_k,
            "_source": False,
            "query": {
                "multi_match": {
                    "query": query,
                    "fields": ["content^1.0", "title^2.0", "section^1.5"],
                    "type": "best_fields",
                }
            },
        }
        try:
            async with httpx.AsyncClient(timeout=10, auth=self.auth) as client:
                resp = await client.post(
                    f"{self.url}/{settings.es_index}/_search",
                    json=body,
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
                hits = resp.json().get("hits", {}).get("hits", [])
            return [(h["_id"], float(h["_score"])) for h in hits]
        except Exception as exc:
            logger.warning("Elasticsearch 检索失败，降级为本地 BM25: %s", exc)
            return []

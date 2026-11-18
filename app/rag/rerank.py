"""Reranker（可选）：调用兼容 bge-reranker 的 HTTP 服务对候选文档重排。"""
from __future__ import annotations

import logging
from typing import List

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class Reranker:
    def __init__(self) -> None:
        self.enabled = bool(settings.rerank_api_url)
        self.url = settings.rerank_api_url.rstrip("/")

    async def rerank(self, query: str, documents: List[str], top_n: int) -> List[tuple[int, float]]:
        if not self.enabled or not documents:
            return []
        url = self.url if self.url.endswith("/rerank") else self.url + "/rerank"
        headers = {"Content-Type": "application/json"}
        if settings.rerank_api_key:
            headers["Authorization"] = f"Bearer {settings.rerank_api_key}"
        payload = {"model": settings.rerank_model, "query": query, "documents": documents, "top_n": top_n}
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
            return [(int(r["index"]), float(r["relevance_score"])) for r in data.get("results", [])]
        except Exception as exc:
            logger.warning("Reranker 调用失败，保留 RRF 排序: %s", exc)
            return []

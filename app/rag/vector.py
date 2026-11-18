"""Embedding 客户端与 Milvus 向量检索。"""
from __future__ import annotations

import logging
from typing import List, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class EmbeddingClient:
    """兼容 OpenAI /v1/embeddings 协议的向量化客户端。"""

    def __init__(self) -> None:
        self.enabled = settings.embedding_enabled
        self.url = settings.embedding_base_url.rstrip("/") + "/embeddings"

    async def embed(self, texts: List[str]) -> List[List[float]]:
        if not self.enabled:
            raise RuntimeError("未配置 Embedding 服务")
        headers = {"Authorization": f"Bearer {settings.embedding_api_key}"}
        payload = {"model": settings.embedding_model, "input": texts, "encoding_format": "float"}
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(self.url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()["data"]
        return [item["embedding"] for item in sorted(data, key=lambda x: x.get("index", 0))]


class MilvusStore:
    def __init__(self) -> None:
        self.uri = settings.milvus_uri
        self.enabled = bool(self.uri)
        self._client = None
        self._embedder = EmbeddingClient()

    def _get_client(self):
        if self._client is None:
            from pymilvus import MilvusClient

            kwargs = {"uri": self.uri}
            if settings.milvus_token:
                kwargs["token"] = settings.milvus_token
            self._client = MilvusClient(**kwargs)
        return self._client

    @property
    def searchable(self) -> bool:
        return self.enabled and self._embedder.enabled

    async def search(self, query: str, top_k: int = 12) -> List[tuple[str, float]]:
        """返回 (chunk_id, 相似度)，失败时返回空列表降级为纯 BM25。"""
        if not self.searchable:
            return []
        try:
            import asyncio

            vectors = await self._embedder.embed([query])
            return await asyncio.to_thread(self._search_sync, vectors[0], top_k)
        except Exception as exc:
            logger.warning("Milvus 检索失败，降级为 BM25: %s", exc)
            return []

    def _search_sync(self, vector: List[float], top_k: int) -> List[tuple[str, float]]:
        client = self._get_client()
        if not client.has_collection(settings.milvus_collection):
            logger.warning("Milvus collection 不存在，请先运行知识库入库脚本")
            return []
        results = client.search(
            collection_name=settings.milvus_collection,
            data=[vector],
            anns_field="vector",
            limit=top_k,
            output_fields=["title", "section", "source", "content"],
        )
        hits: List[tuple[str, float]] = []
        for row in results[0] if results else []:
            hits.append((row["id"], float(row["distance"])))
        return hits

    async def ensure_and_insert(self, records: List[dict]) -> int:
        """建集合 + 批量写入（供入库脚本使用）。"""
        if not self.searchable:
            raise RuntimeError("Milvus 或 Embedding 未配置")
        vectors = await self._embedder.embed([r["content"] for r in records])
        rows = [
            {
                "id": r["id"],
                "vector": vec,
                "title": r["title"],
                "section": r["section"],
                "source": r["source"],
                "content": r["content"],
            }
            for r, vec in zip(records, vectors)
        ]
        return await self._insert_sync(rows)

    def _insert_sync(self, rows: List[dict]) -> int:
        client = self._get_client()
        if client.has_collection(settings.milvus_collection):
            client.drop_collection(settings.milvus_collection)
        client.create_collection(
            collection_name=settings.milvus_collection,
            dimension=settings.embedding_dim,
            primary_field_name="id",
            id_type="string",
            max_length=64,
            vector_field_name="vector",
            metric_type="COSINE",
            enable_dynamic_field=True,
        )
        client.insert(collection_name=settings.milvus_collection, data=rows)
        return len(rows)


def get_milvus_store() -> Optional[MilvusStore]:
    return MilvusStore()

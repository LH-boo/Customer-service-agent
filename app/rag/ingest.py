"""知识库入库脚本：把 Markdown 切片写入 Milvus 与 Elasticsearch。

用法：
    python -m app.rag.ingest
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys

import httpx

from app.config import settings
from app.rag.vector import MilvusStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def index_elasticsearch(chunks: list[dict]) -> None:
    if not settings.es_url:
        logger.info("未配置 Elasticsearch，跳过索引")
        return
    url = settings.es_url.rstrip("/")
    auth = (settings.es_username, settings.es_password) if settings.es_username else None
    lines: list[str] = []
    for c in chunks:
        lines.append('{"index":{"_index":"%s","_id":"%s"}}' % (settings.es_index, c["id"]))
        lines.append(
            json.dumps(
                {"title": c["title"], "section": c["section"], "source": c["source"], "content": c["content"]},
                ensure_ascii=False,
            )
        )
    body = "\n".join(lines) + "\n"
    async with httpx.AsyncClient(timeout=30, auth=auth) as client:
        await client.put(
            f"{url}/{settings.es_index}",
            json={"mappings": {"properties": {"title": {"type": "text"}, "section": {"type": "text"}, "source": {"type": "keyword"}, "content": {"type": "text"}}}},
            headers={"Content-Type": "application/json"},
        )
        resp = await client.post(
            f"{url}/_bulk?refresh=true",
            content=body.encode("utf-8"),
            headers={"Content-Type": "application/x-ndjson"},
        )
        resp.raise_for_status()
    logger.info("Elasticsearch 索引完成：%d 条", len(chunks))


async def main() -> None:
    from app.rag.loader import load_chunks

    chunks = load_chunks(settings.knowledge_path)
    if not chunks:
        logger.error("知识库为空，请检查 KNOWLEDGE_DIR")
        sys.exit(1)
    records = [c.to_dict() for c in chunks]

    store = MilvusStore()
    if store.searchable:
        count = await store.ensure_and_insert(records)
        logger.info("Milvus 入库完成：%d 条", count)
    else:
        logger.info("未配置 Milvus/Embedding，跳过向量入库（检索仍可使用本地 BM25）")

    await index_elasticsearch(records)


if __name__ == "__main__":
    asyncio.run(main())

"""FastAPI 应用入口：对话、工单、鉴权接口与静态前端。"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.agent.service import agent_service
from app.api import auth, chat, tickets
from app.config import settings
from app.database import init_db
from app.rag.pipeline import retriever
from app.schemas import HealthResponse
from app.services.cache import cache

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("启动 %s", settings.app_name)
    await init_db(seed=True)
    await cache.connect()
    retriever.load()
    await agent_service.startup()
    logger.info("服务就绪：http://%s:%s", settings.host, settings.port)
    yield
    await agent_service.shutdown()
    await cache.aclose()
    logger.info("服务已关闭")


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="面向医院患者服务中心的智能客服工单 Agent：RAG + MCP + LangGraph",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.app_env == "dev" else [],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(tickets.router)


@app.get("/health", response_model=HealthResponse, tags=["system"], summary="健康检查")
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        app=settings.app_name,
        llm_enabled=settings.llm_enabled,
        mcp_mode=settings.mcp_mode,
        cache_backend=cache.backend,
        knowledge_chunks=retriever.chunk_count,
        details={
            "database": "sqlite" if settings.database_is_sqlite else "mysql",
            "milvus": bool(settings.milvus_uri and settings.embedding_enabled),
            "elasticsearch": bool(settings.es_url),
            "reranker": bool(settings.rerank_api_url),
        },
    )


if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )

"""RAG 混合检索测试（无需 Milvus/ES，使用本地 BM25）。"""
import pytest

from app.rag.pipeline import retriever


@pytest.fixture(scope="module")
def loaded():
    retriever.load()
    return retriever


@pytest.mark.asyncio
async def test_insurance_retrieval(loaded):
    chunks = await loaded.retrieve("门诊做检查可以医保报销吗")
    assert chunks, "应检索到医保相关制度"
    joined = " ".join(c.chunk.content for c in chunks)
    assert "报销" in joined or "医保" in joined


@pytest.mark.asyncio
async def test_cancel_rule_retrieval(loaded):
    chunks = await loaded.retrieve("预约可以提前多久取消")
    assert chunks
    joined = " ".join(c.chunk.title + c.chunk.content for c in chunks)
    assert "取消" in joined or "退号" in joined


@pytest.mark.asyncio
async def test_irrelevant_question_returns_hits_or_empty(loaded):
    chunks = await loaded.retrieve("今天天气怎么样")
    assert isinstance(chunks, list)

"""混合检索流水线：BM25/ES 关键词召回 + Milvus 语义召回 → RRF 融合 → Reranker 重排。"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

from app.config import settings
from app.rag.bm25 import BM25Index
from app.rag.es import ESStore
from app.rag.loader import Chunk, load_chunks
from app.rag.rerank import Reranker
from app.rag.vector import MilvusStore

logger = logging.getLogger(__name__)

RRF_K = 60

# 查询扩展：把口语化表达映射到知识库用语，提升召回率
QUERY_EXPANSIONS = {
    "第一次": "首次 初次 就诊准备",
    "带什么": "准备 材料 证件",
    "要带": "准备 材料 证件",
    "报销": "医保 报销比例 目录",
    "多少钱": "费用 收费 价格",
    "太贵": "费用 明细 复核",
    "挂号": "预约 挂号 号源",
    "退号": "取消 退号 退费",
    "报告": "检查报告 出具 查询",
    "投诉": "投诉 处理流程 受理",
    "态度": "投诉 服务态度 处理",
    "医生没来": "停诊 变更 通知",
    "哪个科": "科室 就诊 指引",
    "几点": "门诊时间 开放时间",
}


@dataclass
class RetrievedChunk:
    chunk: Chunk
    score: float
    coverage: float

    def to_source(self) -> dict:
        return {
            "title": self.chunk.title,
            "source": self.chunk.source,
            "section": self.chunk.section,
            "snippet": self.chunk.content[:180].replace("\n", " ") + ("..." if len(self.chunk.content) > 180 else ""),
            "score": round(self.score, 4),
        }


def expand_query(query: str) -> str:
    extra = [synonyms for key, synonyms in QUERY_EXPANSIONS.items() if key in query]
    return query + (" " + " ".join(extra) if extra else "")


class HybridRetriever:
    def __init__(self) -> None:
        self.chunks: List[Chunk] = []
        self._chunk_map: Dict[str, Chunk] = {}
        self._bm25: Optional[BM25Index] = None
        self._milvus = MilvusStore()
        self._es = ESStore()
        self._reranker = Reranker()
        self._loaded = False

    def load(self) -> None:
        self.chunks = load_chunks(settings.knowledge_path)
        self._chunk_map = {c.id: c for c in self.chunks}
        self._bm25 = (
            BM25Index(
                documents=[f"{c.title} {c.section} {c.content}" for c in self.chunks],
                ids=[c.id for c in self.chunks],
                metadatas=[c.to_dict() for c in self.chunks],
            )
            if self.chunks
            else None
        )
        self._loaded = True

    def ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    @property
    def chunk_count(self) -> int:
        self.ensure_loaded()
        return len(self.chunks)

    async def retrieve(self, query: str, top_k: Optional[int] = None) -> List[RetrievedChunk]:
        self.ensure_loaded()
        if not self._bm25 or not query.strip():
            return []

        top_k = top_k or settings.rag_top_k
        candidate_k = settings.rag_candidate_k
        expanded = expand_query(query)

        keyword_hits = self._bm25.search(expanded, candidate_k)
        es_hits = await self._es.search(query, candidate_k)
        vector_hits = await self._milvus.search(query, candidate_k)

        # RRF 融合分数（多路召回时使用）
        fused: Dict[str, float] = {}
        for source_hits in (keyword_hits, es_hits, vector_hits):
            for rank, (doc_id, _score) in enumerate(source_hits, start=1):
                if doc_id not in self._chunk_map:
                    continue
                fused[doc_id] = fused.get(doc_id, 0.0) + 1.0 / (RRF_K + rank)
        if not fused:
            return []
        ranked_ids = sorted(fused, key=lambda i: fused[i], reverse=True)[: candidate_k * 2]

        # 单路召回：直接使用该路原始分数，避免 RRF 把同源文档压成近似平局
        single_source = [hits for hits in (keyword_hits, es_hits, vector_hits) if hits]
        if len(single_source) == 1:
            hits = single_source[0]
            max_raw = max(score for _id, score in hits) or 1.0
            candidates = [
                RetrievedChunk(
                    chunk=self._chunk_map[doc_id],
                    score=score / max_raw,
                    coverage=self._bm25.coverage(query, doc_id),
                )
                for doc_id, score in hits
                if doc_id in self._chunk_map
            ]
            candidates.sort(key=lambda c: c.score, reverse=True)
            top_score = candidates[0].score if candidates else 0.0
            candidates = [
                c for c in candidates if c.score >= max(settings.rag_min_score, 0.45 * top_score)
            ] or candidates[:1]
        else:
            # 多路召回：RRF 融合 + 各路相关度归一化，兼顾排序与分数可解释性
            bm25_raw = dict(keyword_hits)
            vector_raw = dict(vector_hits)
            max_kw = max(bm25_raw.values(), default=0.0)
            max_rrf = max(fused.values(), default=1.0)
            candidates = []
            for doc_id in ranked_ids:
                kw = bm25_raw.get(doc_id, 0.0) / max_kw if max_kw else 0.0
                vec = max(0.0, min(1.0, vector_raw.get(doc_id, 0.0)))
                score = 0.5 * (fused[doc_id] / max_rrf) + 0.5 * max(kw, vec)
                candidates.append(
                    RetrievedChunk(
                        chunk=self._chunk_map[doc_id],
                        score=score,
                        coverage=self._bm25.coverage(query, doc_id),
                    )
                )
            candidates.sort(key=lambda c: c.score, reverse=True)
            top_score = candidates[0].score if candidates else 0.0
            candidates = [c for c in candidates if c.score >= max(0.3, 0.45 * top_score)] or candidates[:1]

        if not candidates:
            return []

        # Reranker 重排（可选）
        reranked = await self._reranker.rerank(
            query, [c.chunk.content for c in candidates[: candidate_k]], top_n=top_k
        )
        if reranked:
            candidates = [candidates[i] for i, _score in reranked if i < len(candidates)]

        return candidates[:top_k]

    @staticmethod
    def build_context(chunks: List[RetrievedChunk]) -> str:
        blocks = []
        for i, c in enumerate(chunks, start=1):
            blocks.append(f"[资料{i}]《{c.chunk.title}》·{c.chunk.section}（来源：{c.chunk.source}）\n{c.chunk.content}")
        return "\n\n".join(blocks)


retriever = HybridRetriever()

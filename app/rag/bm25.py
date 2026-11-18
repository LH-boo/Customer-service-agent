"""中文分词与 BM25 关键词检索（Elasticsearch 不可用时的本地实现）。"""
from __future__ import annotations

import logging
import re
from typing import Iterable, List, Sequence, Tuple

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+|[\u4e00-\u9fa5]+")
_STOPWORDS = {
    "的", "了", "吗", "呢", "吧", "我", "你", "他", "她", "它", "是", "在", "有", "和",
    "怎么", "什么", "如何", "可以", "需要", "请问", "一下", "这个", "那个", "医院",
}

_jieba = None


def _get_jieba():
    global _jieba
    if _jieba is None:
        try:
            import jieba

            jieba.setLogLevel(logging.WARNING)
            _jieba = jieba
        except Exception:
            logger.warning("未安装 jieba，中文检索降级为二元切分")
            _jieba = False
    return _jieba


def tokenize(text: str) -> List[str]:
    text = (text or "").lower()
    tokens: List[str] = []
    jieba = _get_jieba()
    for match in _TOKEN_RE.findall(text):
        if match.isascii():
            if match not in _STOPWORDS:
                tokens.append(match)
            continue
        if jieba:
            words = [w.strip() for w in jieba.lcut_for_search(match) if len(w.strip()) > 1]
        else:
            words = [match[i : i + 2] for i in range(max(len(match) - 1, 1))]
        tokens.extend(w for w in words if w not in _STOPWORDS)
    return tokens


class BM25Index:
    """封装 rank_bm25，提供带原始分数的检索。"""

    def __init__(self, documents: Sequence[str], ids: Sequence[str], metadatas: Sequence[dict]):
        from rank_bm25 import BM25Okapi

        self.ids = list(ids)
        self.metadatas = list(metadatas)
        self.corpus_tokens = [tokenize(doc) for doc in documents]
        self.bm25 = BM25Okapi(self.corpus_tokens) if self.corpus_tokens else None

    def search(self, query: str, top_k: int = 12) -> List[Tuple[str, float]]:
        if not self.bm25 or not self.ids:
            return []
        tokens = tokenize(query)
        if not tokens:
            return []
        scores = self.bm25.get_scores(tokens)
        ranked = sorted(zip(self.ids, scores), key=lambda x: x[1], reverse=True)[:top_k]
        return [(doc_id, float(score)) for doc_id, score in ranked if score > 0]

    def coverage(self, query: str, doc_id: str) -> float:
        """查询词在文档中的覆盖率，用于「知识库是否有可靠依据」的判定。"""
        tokens = set(tokenize(query))
        if not tokens:
            return 0.0
        try:
            idx = self.ids.index(doc_id)
        except ValueError:
            return 0.0
        doc_tokens = set(self.corpus_tokens[idx])
        return len(tokens & doc_tokens) / len(tokens)


def token_set(text: str) -> set[str]:
    return set(tokenize(text))


def jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)

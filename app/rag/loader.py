"""知识库文档加载与切分：按 Markdown 标题切块，保留可追溯来源。"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)

MAX_CHUNK_CHARS = 900


@dataclass
class Chunk:
    id: str
    title: str          # 文档标题
    section: str       # 章节标题
    source: str        # 文件名
    content: str
    tokens: List[str] = field(default_factory=list)

    def citation(self) -> str:
        return f"《{self.title}》·{self.section}"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "section": self.section,
            "source": self.source,
            "content": self.content,
        }


def _chunk_id(source: str, section: str, index: int) -> str:
    raw = f"{source}#{section}#{index}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:16]


def _split_long(text: str, limit: int = MAX_CHUNK_CHARS) -> List[str]:
    if len(text) <= limit:
        return [text]
    parts, buf = [], ""
    for para in text.split("\n\n"):
        if len(buf) + len(para) + 2 > limit and buf:
            parts.append(buf.strip())
            buf = para
        else:
            buf = f"{buf}\n\n{para}" if buf else para
    if buf.strip():
        parts.append(buf.strip())
    return parts


def load_chunks(knowledge_dir: Path) -> List[Chunk]:
    """读取知识目录下所有 .md 文件，按二级标题切片。"""
    chunks: List[Chunk] = []
    if not knowledge_dir.exists():
        logger.warning("知识库目录不存在: %s", knowledge_dir)
        return chunks

    for path in sorted(knowledge_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        doc_title = path.stem
        sections: list[tuple[str, list[str]]] = []
        current_title, current_lines = "概述", []

        for line in text.splitlines():
            if line.startswith("# ") and not line.startswith("## "):
                doc_title = line[2:].strip() or doc_title
            elif line.startswith("## "):
                if current_lines and any(l.strip() for l in current_lines):
                    sections.append((current_title, current_lines))
                current_title, current_lines = line[3:].strip(), []
            else:
                current_lines.append(line)
        if current_lines and any(l.strip() for l in current_lines):
            sections.append((current_title, current_lines))

        for section, lines in sections:
            body = "\n".join(lines).strip()
            if len(body) < 20:
                continue
            for i, part in enumerate(_split_long(body)):
                chunks.append(
                    Chunk(
                        id=_chunk_id(path.name, section, i),
                        title=doc_title,
                        section=section,
                        source=path.name,
                        content=part,
                    )
                )
    logger.info("知识库加载完成：%d 个文件，%d 个切片", len(list(knowledge_dir.glob("*.md"))), len(chunks))
    return chunks

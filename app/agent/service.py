"""Agent 运行时：负责图编译、Checkpointer 生命周期与单轮对话执行。"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.agent.graph import build_graph
from app.config import BASE_DIR

logger = logging.getLogger(__name__)


class AgentService:
    def __init__(self) -> None:
        self.graph = None
        self._cm = None

    async def startup(self) -> None:
        saver = None
        try:
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

            checkpoint_path = BASE_DIR / "data" / "checkpoints.sqlite"
            checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            self._cm = AsyncSqliteSaver.from_conn_string(str(checkpoint_path))
            saver = await self._cm.__aenter__()
            logger.info("LangGraph Checkpointer: SQLite (%s)", checkpoint_path)
        except Exception as exc:
            from langgraph.checkpoint.memory import MemorySaver

            saver = MemorySaver()
            self._cm = None
            logger.warning("Checkpointer 初始化失败，改用内存模式: %s", exc)

        self.graph = build_graph(saver)

    async def shutdown(self) -> None:
        if self._cm is not None:
            try:
                await self._cm.__aexit__(None, None, None)
            except Exception:
                pass
            self._cm = None

    async def run(
        self,
        patient_id: int,
        patient_name: str,
        session_id: str,
        question: str,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        assert self.graph is not None, "Agent 尚未初始化"
        initial = {
            "session_id": session_id,
            "patient_id": patient_id,
            "patient_name": patient_name,
            "question": question,
            "history": history or [],
            # 每轮重置的字段（pending_action 不重置，用于跨轮确认）
            "intent": "",
            "category": "",
            "department": "",
            "priority": "normal",
            "reason": "",
            "rag_context": "",
            "sources": [],
            "tool_name": None,
            "tool_result": None,
            "tool_transport": "",
            "ticket_id": None,
            "ticket_status": None,
            "need_human": False,
            "emergency": False,
            "direct_reply": False,
            "error": None,
            "answer": "",
            "trace": [],
        }
        config = {
            "configurable": {"thread_id": f"patient:{patient_id}:session:{session_id}"},
            "recursion_limit": 20,
        }
        return await self.graph.ainvoke(initial, config=config)


agent_service = AgentService()

"""LangGraph 状态定义：节点之间共享的业务上下文。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class TicketState(TypedDict, total=False):
    # 会话与身份
    session_id: str
    patient_id: int
    patient_name: str
    question: str
    history: List[Dict[str, str]]

    # 分类结果
    intent: str
    category: str
    department: str
    priority: str
    reason: str

    # 检索与工具结果
    rag_context: str
    sources: List[Dict[str, Any]]
    tool_name: Optional[str]
    tool_result: Optional[Dict[str, Any]]
    tool_transport: str

    # 工单
    ticket_id: Optional[str]
    ticket_status: Optional[str]

    # 流程控制
    need_human: bool
    emergency: bool
    direct_reply: bool
    pending_action: Optional[Dict[str, Any]]
    error: Optional[str]

    answer: str
    trace: List[str]

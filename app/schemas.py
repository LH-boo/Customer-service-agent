"""对外 API 的数据结构定义。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class LoginRequest(BaseModel):
    patient_no: str = Field(..., min_length=1, max_length=32, examples=["P2026001"])
    phone: str = Field(..., min_length=4, max_length=32, examples=["13800000001"])


class PatientOut(BaseModel):
    id: int
    patient_no: str
    name: str
    phone_masked: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    patient: PatientOut


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    session_id: Optional[str] = Field(default=None, max_length=64)

    @field_validator("message")
    @classmethod
    def strip_message(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("消息不能为空")
        return v


class SourceOut(BaseModel):
    title: str
    source: str
    section: str
    snippet: str
    score: float = 0.0


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    intent: str
    intent_label: str
    priority: str
    ticket_id: Optional[str] = None
    ticket_status: Optional[str] = None
    need_human: bool = False
    emergency: bool = False
    sources: List[SourceOut] = Field(default_factory=list)
    trace: List[str] = Field(default_factory=list)
    cached: bool = False


class TicketLogOut(BaseModel):
    operator: str
    action: str
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


class TicketListItem(BaseModel):
    ticket_no: str
    title: str
    category: str
    priority: str
    department: str
    status: str
    need_human: bool
    created_at: datetime
    updated_at: datetime


class TicketDetail(TicketListItem):
    content: str
    logs: List[TicketLogOut] = Field(default_factory=list)


class ConversationOut(BaseModel):
    role: str
    content: str
    intent: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class HealthResponse(BaseModel):
    status: str
    app: str
    llm_enabled: bool
    mcp_mode: str
    cache_backend: str
    knowledge_chunks: int
    details: Dict[str, Any] = Field(default_factory=dict)

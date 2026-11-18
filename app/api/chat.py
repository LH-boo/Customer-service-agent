"""在线客服对话接口。"""
from __future__ import annotations

import logging
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.classifier import RULE_FAQ_INTENTS, classify_by_rules
from app.agent.service import agent_service
from app.constants import INTENT_CONFIRM_PENDING, INTENTS
from app.database import get_session
from app.models import Conversation, Patient
from app.schemas import ChatRequest, ChatResponse, ConversationOut
from app.security import get_current_patient
from app.services.cache import cache
from app.utils import mask_sensitive

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])

SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{6,64}$")


@router.post("", response_model=ChatResponse, summary="发送患者问题，返回 Agent 回复")
async def chat(
    payload: ChatRequest,
    patient: Patient = Depends(get_current_patient),
    session: AsyncSession = Depends(get_session),
) -> ChatResponse:
    session_id = payload.session_id if payload.session_id and SESSION_RE.match(payload.session_id) else uuid.uuid4().hex
    question = payload.message

    history = await cache.get_session_history(patient.id, session_id)

    # FAQ 缓存：仅对公共知识类问题启用，个性化数据与确认类操作永不缓存
    quick_intent, _ = classify_by_rules(question)
    cacheable = quick_intent in RULE_FAQ_INTENTS and len(question) > 6
    if cacheable:
        cached = await cache.get_faq(question)
        if cached:
            await _save_turn(session, patient.id, session_id, question, cached["answer"], cached["intent"])
            await cache.append_session_message(patient.id, session_id, "user", mask_sensitive(question), cached["intent"])
            await cache.append_session_message(patient.id, session_id, "assistant", cached["answer"], cached["intent"])
            return ChatResponse(
                session_id=session_id,
                answer=cached["answer"],
                intent=cached["intent"],
                intent_label=cached["intent_label"],
                priority=cached.get("priority", "normal"),
                need_human=False,
                sources=cached.get("sources", []),
                trace=["cache：命中高频问答缓存，直接返回标准答案"],
                cached=True,
            )

    try:
        result = await agent_service.run(
            patient_id=patient.id,
            patient_name=patient.name,
            session_id=session_id,
            question=question,
            history=history,
        )
    except Exception as exc:
        logger.exception("Agent 执行异常")
        raise HTTPException(status_code=500, detail="智能客服暂时不可用，请稍后重试或联系人工客服")

    intent = result.get("intent") or quick_intent
    if intent == INTENT_CONFIRM_PENDING:
        intent = "appointment_cancel"
    meta = INTENTS.get(intent, INTENTS["other"])
    answer = result.get("answer", "")
    sources = result.get("sources") or []
    trace = result.get("trace") or []

    await _save_turn(session, patient.id, session_id, question, answer, intent)
    await cache.append_session_message(patient.id, session_id, "user", mask_sensitive(question), intent)
    await cache.append_session_message(patient.id, session_id, "assistant", answer, intent)

    if cacheable and sources and not result.get("ticket_id") and not result.get("need_human"):
        await cache.set_faq(
            question,
            {
                "answer": answer,
                "intent": intent,
                "intent_label": meta["label"],
                "priority": result.get("priority", "normal"),
                "sources": sources,
            },
        )

    return ChatResponse(
        session_id=session_id,
        answer=answer,
        intent=intent,
        intent_label=meta["label"],
        priority=result.get("priority", "normal"),
        ticket_id=result.get("ticket_id"),
        ticket_status=result.get("ticket_status"),
        need_human=bool(result.get("need_human")),
        emergency=bool(result.get("emergency")),
        sources=sources,
        trace=trace,
    )


async def _save_turn(
    session: AsyncSession,
    patient_id: int,
    session_id: str,
    question: str,
    answer: str,
    intent: str,
) -> None:
    session.add(
        Conversation(
            session_id=session_id,
            patient_id=patient_id,
            role="user",
            content=mask_sensitive(question),
            intent=intent,
        )
    )
    session.add(
        Conversation(
            session_id=session_id,
            patient_id=patient_id,
            role="assistant",
            content=answer,
            intent=intent,
        )
    )
    await session.commit()


@router.get("/history", response_model=list[ConversationOut], summary="查询会话历史")
async def history(
    session_id: str,
    patient: Patient = Depends(get_current_patient),
    session: AsyncSession = Depends(get_session),
) -> list[ConversationOut]:
    from sqlalchemy import select

    rows = (
        await session.scalars(
            select(Conversation)
            .where(Conversation.patient_id == patient.id, Conversation.session_id == session_id)
            .order_by(Conversation.id.asc())
            .limit(200)
        )
    ).all()
    return [ConversationOut.model_validate(r) for r in rows]

"""工单查询接口：仅返回当前登录患者本人的工单。"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.models import Patient, Ticket, TicketLog
from app.schemas import TicketDetail, TicketListItem, TicketLogOut
from app.security import get_current_patient
from app.services.cache import cache

router = APIRouter(prefix="/api/tickets", tags=["tickets"])


def _to_item(ticket: Ticket) -> TicketListItem:
    return TicketListItem(
        ticket_no=ticket.ticket_no,
        title=ticket.title,
        category=ticket.category,
        priority=ticket.priority,
        department=ticket.department,
        status=ticket.status,
        need_human=ticket.need_human,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
    )


@router.get("", response_model=List[TicketListItem], summary="我的工单列表")
async def list_tickets(
    status: Optional[str] = Query(default=None, description="按状态过滤"),
    limit: int = Query(default=20, ge=1, le=100),
    patient: Patient = Depends(get_current_patient),
    session: AsyncSession = Depends(get_session),
) -> List[TicketListItem]:
    stmt = select(Ticket).where(Ticket.patient_id == patient.id)
    if status:
        stmt = stmt.where(Ticket.status == status)
    stmt = stmt.order_by(Ticket.updated_at.desc()).limit(limit)
    rows = (await session.scalars(stmt)).all()
    return [_to_item(t) for t in rows]


@router.get("/{ticket_no}", response_model=TicketDetail, summary="工单详情与流转记录")
async def ticket_detail(
    ticket_no: str,
    patient: Patient = Depends(get_current_patient),
    session: AsyncSession = Depends(get_session),
) -> TicketDetail:
    cache_key = cache.ticket_key(patient.id, ticket_no)
    cached = await cache.get_json(cache_key)
    if cached:
        return TicketDetail(**cached)

    ticket = await session.scalar(
        select(Ticket).where(Ticket.ticket_no == ticket_no, Ticket.patient_id == patient.id)
    )
    if ticket is None:
        raise HTTPException(status_code=404, detail="工单不存在或无权访问")

    logs = (
        await session.scalars(
            select(TicketLog).where(TicketLog.ticket_id == ticket.id).order_by(TicketLog.created_at.asc())
        )
    ).all()

    detail = TicketDetail(
        **_to_item(ticket).model_dump(),
        content=ticket.content,
        logs=[TicketLogOut.model_validate(log) for log in logs],
    )
    await cache.set_json(cache_key, detail.model_dump(mode="json"), settings.ticket_cache_ttl)
    return detail

"""医院业务服务层：所有工具（MCP Tool）最终都调用这里，统一做身份与权限校验。

设计原则：
1. 每个查询/操作都必须携带 patient_id，并在 SQL 层按 patient_id 过滤，防止越权；
2. 有副作用的操作（取消预约、创建工单）必须校验业务状态与规则；
3. 返回结构化 dict，便于 MCP 传输与 LLM 二次组织语言。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants import (
    APPOINTMENT_STATUS_LABELS,
    REPORT_STATUS_LABELS,
    TICKET_STATUS_LABELS,
)
from app.database import SessionLocal
from app.models import Appointment, Charge, Department, Patient, Report, Ticket, TicketLog
from app.utils import fmt_dt, gen_no

logger = logging.getLogger(__name__)


def _ok(**kwargs: Any) -> dict:
    return {"ok": True, **kwargs}


def _err(message: str, **kwargs: Any) -> dict:
    return {"ok": False, "error": message, **kwargs}


async def _get_patient(session: AsyncSession, patient_id: int) -> Patient | None:
    return await session.get(Patient, patient_id)


async def get_appointments(
    patient_id: int,
    appointment_no: Optional[str] = None,
    include_history: bool = False,
) -> dict:
    """查询患者本人预约记录。"""
    async with SessionLocal() as session:
        patient = await _get_patient(session, patient_id)
        if not patient:
            return _err("未找到患者信息")

        stmt = select(Appointment).where(Appointment.patient_id == patient_id)
        if appointment_no:
            stmt = stmt.where(Appointment.appointment_no == appointment_no)
        if not include_history:
            stmt = stmt.where(Appointment.status == "booked")
        stmt = stmt.order_by(Appointment.appointment_time.asc()).limit(10)
        rows = (await session.scalars(stmt)).all()

        return _ok(
            patient_name=patient.name,
            count=len(rows),
            appointments=[
                {
                    "appointment_id": a.id,
                    "appointment_no": a.appointment_no,
                    "department": a.department,
                    "doctor_name": a.doctor_name or "普通门诊",
                    "appointment_time": fmt_dt(a.appointment_time),
                    "status": a.status,
                    "status_label": APPOINTMENT_STATUS_LABELS.get(a.status, a.status),
                    "cancel_deadline": fmt_dt(a.appointment_time - timedelta(hours=settings.cancel_min_hours)),
                }
                for a in rows
            ],
        )


async def cancel_appointment(
    patient_id: int,
    appointment_id: int,
    operator: str = "智能客服 Agent",
) -> dict:
    """取消预约：校验归属、状态与取消时限后执行。"""
    async with SessionLocal() as session:
        appt = await session.scalar(
            select(Appointment).where(
                Appointment.id == appointment_id,
                Appointment.patient_id == patient_id,
            )
        )
        if not appt:
            return _err("未找到该预约，或该预约不属于当前登录患者")
        if appt.status != "booked":
            return _err(f"该预约当前状态为「{APPOINTMENT_STATUS_LABELS.get(appt.status, appt.status)}」，无法取消")
        if appt.appointment_time - datetime.now() < timedelta(hours=settings.cancel_min_hours):
            return _err(
                f"距就诊时间不足 {settings.cancel_min_hours} 小时，按医院规定需联系人工客服办理",
                need_human=True,
            )

        appt.status = "cancelled"
        await session.commit()
        logger.info("患者 %s 取消预约 %s，操作人=%s", patient_id, appt.appointment_no, operator)
        return _ok(
            appointment_no=appt.appointment_no,
            department=appt.department,
            doctor_name=appt.doctor_name or "普通门诊",
            appointment_time=fmt_dt(appt.appointment_time),
            message="预约已取消，号源已释放。",
        )


async def get_report_status(
    patient_id: int,
    report_no: Optional[str] = None,
    item_keyword: Optional[str] = None,
) -> dict:
    """查询本人检查报告状态（不返回报告结论）。"""
    async with SessionLocal() as session:
        stmt = select(Report).where(Report.patient_id == patient_id)
        if report_no:
            stmt = stmt.where(Report.report_no == report_no)
        if item_keyword:
            stmt = stmt.where(Report.item_name.contains(item_keyword))
        stmt = stmt.order_by(Report.updated_at.desc()).limit(10)
        rows = (await session.scalars(stmt)).all()
        if not rows:
            return _err("未查询到相关检查报告，请确认报告单号或联系检验科")

        return _ok(
            count=len(rows),
            reports=[
                {
                    "report_no": r.report_no,
                    "item_name": r.item_name,
                    "department": r.department,
                    "report_status": r.status,
                    "status_label": REPORT_STATUS_LABELS.get(r.status, r.status),
                    "updated_at": fmt_dt(r.updated_at),
                }
                for r in rows
            ],
            notice="报告状态以医院系统为准；报告解读请咨询开单医生。",
        )


async def get_department_info(keyword: Optional[str] = None, department_name: Optional[str] = None) -> dict:
    """查询科室位置、简介与联系方式。"""
    async with SessionLocal() as session:
        stmt = select(Department)
        if department_name:
            stmt = stmt.where(Department.name == department_name)
        elif keyword:
            stmt = stmt.where(
                Department.name.contains(keyword) | Department.description.contains(keyword)
            )
        rows = (await session.scalars(stmt.limit(8))).all()
        if not rows:
            return _err("未找到匹配的科室，可通过门诊服务中心电话咨询")
        return _ok(
            count=len(rows),
            departments=[
                {
                    "name": d.name,
                    "location": d.location,
                    "phone": d.phone,
                    "description": d.description,
                }
                for d in rows
            ],
            notice="科室选择建议仅供参考，具体请以门诊分诊台意见为准。",
        )


async def get_charge_detail(patient_id: int, visit_no: Optional[str] = None) -> dict:
    """查询本人费用明细。"""
    async with SessionLocal() as session:
        stmt = select(Charge).where(Charge.patient_id == patient_id)
        if visit_no:
            stmt = stmt.where(Charge.visit_no == visit_no)
        rows = (await session.scalars(stmt.order_by(Charge.charged_at.desc()).limit(20))).all()
        if not rows:
            return _err("未查询到费用记录")

        total = float(sum(float(r.amount) for r in rows))
        insurance = float(sum(float(r.insurance_amount or 0) for r in rows))
        return _ok(
            visit_no=rows[0].visit_no,
            items=[
                {
                    "item_name": r.item_name,
                    "category": r.category,
                    "amount": float(r.amount),
                    "insurance_amount": float(r.insurance_amount or 0),
                    "self_pay": float(r.amount) - float(r.insurance_amount or 0),
                    "charged_at": fmt_dt(r.charged_at),
                }
                for r in rows
            ],
            total_amount=round(total, 2),
            insurance_amount=round(insurance, 2),
            self_pay_amount=round(total - insurance, 2),
            fee_dispute_threshold=settings.fee_dispute_amount,
        )


async def create_ticket(
    patient_id: int,
    title: str,
    content: str,
    category: str,
    priority: str = "normal",
    department: Optional[str] = None,
    need_human: bool = False,
    operator: str = "智能客服 Agent",
) -> dict:
    """创建患者服务工单，并写入首条流转记录。"""
    from app.constants import INTENTS

    default_department = "门诊服务中心"
    for meta in INTENTS.values():
        if meta["category"] == category:
            default_department = meta["department"]
            break

    async with SessionLocal() as session:
        patient = await _get_patient(session, patient_id)
        if not patient:
            return _err("未找到患者信息，无法创建工单")

        ticket = Ticket(
            ticket_no=gen_no("TK"),
            patient_id=patient_id,
            title=title[:240],
            content=content,
            category=category,
            priority=priority,
            department=department or default_department,
            status="waiting_human" if need_human else "pending",
            need_human=need_human,
            source="agent",
        )
        session.add(ticket)
        await session.flush()
        session.add(
            TicketLog(
                ticket_id=ticket.id,
                operator=operator,
                action="create",
                content=f"由智能客服根据患者问题自动创建工单，分配给{ticket.department}。",
            )
        )
        await session.commit()
        return _ok(
            ticket_id=ticket.ticket_no,
            ticket_no=ticket.ticket_no,
            title=ticket.title,
            category=ticket.category,
            priority=ticket.priority,
            department=ticket.department,
            status=ticket.status,
            status_label=TICKET_STATUS_LABELS.get(ticket.status, ticket.status),
            created_at=fmt_dt(ticket.created_at),
        )


async def get_ticket_status(patient_id: int, ticket_no: str) -> dict:
    """查询本人工单状态与处理进度。"""
    async with SessionLocal() as session:
        ticket = await session.scalar(
            select(Ticket).where(Ticket.ticket_no == ticket_no, Ticket.patient_id == patient_id)
        )
        if not ticket:
            return _err("未找到该工单，或该工单不属于当前登录患者")
        logs = (
            await session.scalars(
                select(TicketLog).where(TicketLog.ticket_id == ticket.id).order_by(TicketLog.created_at.asc())
            )
        ).all()
        return _ok(
            ticket_no=ticket.ticket_no,
            title=ticket.title,
            category=ticket.category,
            priority=ticket.priority,
            department=ticket.department,
            status=ticket.status,
            status_label=TICKET_STATUS_LABELS.get(ticket.status, ticket.status),
            updated_at=fmt_dt(ticket.updated_at),
            logs=[
                {"operator": l.operator, "action": l.action, "content": l.content, "created_at": fmt_dt(l.created_at)}
                for l in logs
            ],
        )


async def assign_ticket(ticket_no: str, department: str, operator: str = "智能客服 Agent") -> dict:
    """把工单分配给指定处理部门。"""
    async with SessionLocal() as session:
        ticket = await session.scalar(select(Ticket).where(Ticket.ticket_no == ticket_no))
        if not ticket:
            return _err("工单不存在")
        ticket.department = department
        if ticket.status == "pending":
            ticket.status = "waiting_human"
        session.add(
            TicketLog(
                ticket_id=ticket.id,
                operator=operator,
                action="assign",
                content=f"工单已分配给{department}处理。",
            )
        )
        await session.commit()
        return _ok(ticket_no=ticket.ticket_no, department=department, status=ticket.status)


async def add_ticket_comment(
    ticket_no: str,
    content: str,
    operator: str = "系统",
    action: str = "comment",
) -> dict:
    """追加处理记录（用于人工跟进或 Agent 补录业务核查结果）。"""
    async with SessionLocal() as session:
        ticket = await session.scalar(select(Ticket).where(Ticket.ticket_no == ticket_no))
        if not ticket:
            return _err("工单不存在")
        session.add(TicketLog(ticket_id=ticket.id, operator=operator, action=action, content=content))
        await session.commit()
        return _ok(ticket_no=ticket_no, message="处理记录已添加")

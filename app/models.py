"""业务数据模型：患者、科室、预约、报告、费用、工单、工单流转、对话记录。"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# SQLite 下 BIGINT 主键无法自增，用 INTEGER 变体兼容
IDType = BigInteger().with_variant(Integer, "sqlite")


def now() -> datetime:
    return datetime.now()


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(IDType, primary_key=True, autoincrement=True)
    patient_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64))
    phone: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    tickets: Mapped[List["Ticket"]] = relationship(back_populates="patient")
    appointments: Mapped[List["Appointment"]] = relationship(back_populates="patient")
    reports: Mapped[List["Report"]] = relationship(back_populates="patient")


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(IDType, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    code: Mapped[str] = mapped_column(String(32), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    location: Mapped[str] = mapped_column(String(128), default="")
    phone: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Appointment(Base):
    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(IDType, primary_key=True, autoincrement=True)
    appointment_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    department: Mapped[str] = mapped_column(String(64))
    doctor_name: Mapped[str] = mapped_column(String(64), default="")
    appointment_time: Mapped[datetime] = mapped_column(DateTime, index=True)
    status: Mapped[str] = mapped_column(String(24), default="booked")  # booked/cancelled/completed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    patient: Mapped[Patient] = relationship(back_populates="appointments")


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(IDType, primary_key=True, autoincrement=True)
    report_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    item_name: Mapped[str] = mapped_column(String(128), default="")
    department: Mapped[str] = mapped_column(String(64), default="检验科")
    status: Mapped[str] = mapped_column(String(24), default="processing")  # processing/ready/delivered
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    patient: Mapped[Patient] = relationship(back_populates="reports")


class Charge(Base):
    """费用明细（模拟数据，仅用于演示费用咨询与争议转人工）。"""

    __tablename__ = "charges"

    id: Mapped[int] = mapped_column(IDType, primary_key=True, autoincrement=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    visit_no: Mapped[str] = mapped_column(String(32), index=True)
    item_name: Mapped[str] = mapped_column(String(128))
    category: Mapped[str] = mapped_column(String(64), default="检查费")
    amount: Mapped[float] = mapped_column(Numeric(10, 2))
    insurance_amount: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    charged_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(IDType, primary_key=True, autoincrement=True)
    ticket_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(32), index=True)
    priority: Mapped[str] = mapped_column(String(16), default="normal")
    department: Mapped[str] = mapped_column(String(64), default="门诊服务中心")
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    need_human: Mapped[bool] = mapped_column(default=False)
    source: Mapped[str] = mapped_column(String(24), default="agent")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)

    patient: Mapped[Patient] = relationship(back_populates="tickets")
    logs: Mapped[List["TicketLog"]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan", order_by="TicketLog.created_at"
    )


class TicketLog(Base):
    __tablename__ = "ticket_logs"

    id: Mapped[int] = mapped_column(IDType, primary_key=True, autoincrement=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    operator: Mapped[str] = mapped_column(String(64), default="system")
    action: Mapped[str] = mapped_column(String(32), default="create")
    content: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    ticket: Mapped[Ticket] = relationship(back_populates="logs")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(IDType, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user / assistant
    content: Mapped[str] = mapped_column(Text)
    intent: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


Index("ix_tickets_patient_status", Ticket.patient_id, Ticket.status)
Index("ix_conversations_session_time", Conversation.session_id, Conversation.created_at)

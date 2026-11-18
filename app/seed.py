"""演示数据：模拟患者、科室、预约、报告、费用与历史工单。"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Appointment, Charge, Department, Patient, Report, Ticket, TicketLog


async def seed_demo_data(session: AsyncSession) -> None:
    exists = await session.scalar(select(func.count()).select_from(Patient))
    if exists:
        return

    now = datetime.now()
    p1 = Patient(patient_no="P2026001", name="张伟", phone="13800000001")
    p2 = Patient(patient_no="P2026002", name="李静", phone="13800000002")
    session.add_all([p1, p2])
    await session.flush()

    session.add_all(
        [
            Department(name="门诊服务中心", code="MZ", description="负责门诊预约、就医流程、投诉受理与协调。", location="门诊楼 1 层 A 区", phone="0571-88000001"),
            Department(name="内科", code="NK", description="诊治呼吸、消化、心血管、内分泌等内科常见病与多发病。", location="门诊楼 3 层", phone="0571-88000002"),
            Department(name="外科", code="WK", description="诊治普外、骨科、泌尿等外科疾病，提供术前评估与术后随访。", location="门诊楼 4 层", phone="0571-88000003"),
            Department(name="儿科", code="EK", description="0-14 岁儿童常见病、多发病诊治及儿童保健。", location="门诊楼 2 层 B 区", phone="0571-88000004"),
            Department(name="医保办公室", code="YB", description="负责医保政策咨询、门诊慢特病备案、异地就医备案。", location="门诊楼 1 层 12 号窗口", phone="0571-88000005"),
            Department(name="检验科", code="JY", description="血常规、生化、免疫等检验项目的采样与报告发放。", location="医技楼 2 层", phone="0571-88000006"),
            Department(name="财务收费处", code="CW", description="负责挂号收费、费用明细查询与退费办理。", location="门诊楼 1 层 8 号窗口", phone="0571-88000007"),
            Department(name="投诉管理办公室", code="TS", description="受理患者投诉建议，督促整改并回访。", location="行政楼 3 层", phone="0571-88000008"),
        ]
    )

    session.add_all(
        [
            Appointment(appointment_no="AP20260001", patient_id=p1.id, department="内科", doctor_name="王丽华", appointment_time=now + timedelta(days=1, hours=2), status="booked"),
            Appointment(appointment_no="AP20260002", patient_id=p1.id, department="检验科", doctor_name="", appointment_time=now - timedelta(days=6), status="completed"),
            Appointment(appointment_no="AP20260003", patient_id=p1.id, department="内科", doctor_name="李国强", appointment_time=now + timedelta(days=3, hours=4), status="booked"),
            Appointment(appointment_no="AP20260004", patient_id=p2.id, department="儿科", doctor_name="陈晓", appointment_time=now + timedelta(days=1, hours=1), status="booked"),
        ]
    )

    session.add_all(
        [
            Report(report_no="R20261118001", patient_id=p1.id, item_name="血常规（五分类）", department="检验科", status="processing", updated_at=now - timedelta(hours=2)),
            Report(report_no="R20261116002", patient_id=p1.id, item_name="胸部 CT（平扫）", department="放射科", status="ready", updated_at=now - timedelta(days=1)),
            Report(report_no="R20261117003", patient_id=p2.id, item_name="尿常规", department="检验科", status="ready", updated_at=now - timedelta(hours=5)),
        ]
    )

    visit_no = "V" + now.strftime("%Y%m%d") + "001"
    session.add_all(
        [
            Charge(patient_id=p1.id, visit_no=visit_no, item_name="门诊诊察费", category="诊察费", amount=50, insurance_amount=35, charged_at=now - timedelta(hours=4)),
            Charge(patient_id=p1.id, visit_no=visit_no, item_name="血常规（五分类）", category="检查费", amount=180, insurance_amount=126, charged_at=now - timedelta(hours=4)),
            Charge(patient_id=p1.id, visit_no=visit_no, item_name="胸部 CT（平扫）", category="检查费", amount=280, insurance_amount=0, charged_at=now - timedelta(hours=4)),
        ]
    )

    ticket = Ticket(
        ticket_no="TK20261115001",
        patient_id=p1.id,
        title="门诊叫号等待时间过长",
        content="候诊区等待超过 1 小时，希望改进叫号提示。",
        category="投诉建议",
        priority="normal",
        department="门诊服务中心",
        status="resolved",
        need_human=True,
    )
    session.add(ticket)
    await session.flush()
    session.add_all(
        [
            TicketLog(ticket_id=ticket.id, operator="智能客服 Agent", action="create", content="根据患者反馈创建投诉建议工单，转门诊服务中心。"),
            TicketLog(ticket_id=ticket.id, operator="门诊服务中心 · 王敏", action="resolve", content="已电话回访患者，说明叫号规则并致歉，患者表示理解。"),
        ]
    )

    await session.commit()

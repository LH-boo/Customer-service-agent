"""MCP 工具注册表：统一的工具描述、参数 Schema 与执行入口。"""
from __future__ import annotations

from typing import Any, Callable, Dict

from app.services import business as svc


def _patient_schema(extra: Dict[str, Any] | None = None, required: list[str] | None = None) -> dict:
    properties = {
        "patient_id": {"type": "integer", "description": "当前登录患者的内部 ID（由服务端注入，禁止使用模型推测值）"},
    }
    properties.update(extra or {})
    return {"type": "object", "properties": properties, "required": required or ["patient_id"]}


TOOLS: Dict[str, dict] = {
    "get_appointment": {
        "name": "get_appointment",
        "description": "查询当前患者本人的预约记录（科室、医生、就诊时间、状态、取消截止时间）。",
        "parameters": _patient_schema(
            {
                "appointment_no": {"type": "string", "description": "预约单号，可选；不填则返回最近的有效预约"},
                "include_history": {"type": "boolean", "description": "是否包含历史预约，默认 false"},
            }
        ),
        "handler": svc.get_appointments,
        "mutating": False,
        "allowed_intents": ["appointment", "appointment_cancel", "complaint"],
    },
    "cancel_appointment": {
        "name": "cancel_appointment",
        "description": "取消患者本人的预约。必须在患者明确确认、且通过归属/状态/时限校验后才可调用。",
        "parameters": _patient_schema(
            {"appointment_id": {"type": "integer", "description": "预约记录 ID，来自 get_appointment 的结果"}},
            ["patient_id", "appointment_id"],
        ),
        "handler": svc.cancel_appointment,
        "mutating": True,
        "allowed_intents": ["confirm_pending"],
    },
    "get_report_status": {
        "name": "get_report_status",
        "description": "查询当前患者检查报告的处理状态与更新时间，不返回报告结论或诊断。",
        "parameters": _patient_schema(
            {
                "report_no": {"type": "string", "description": "报告单号，可选"},
                "item_keyword": {"type": "string", "description": "检查项目关键词，如 血常规、CT，可选"},
            }
        ),
        "handler": svc.get_report_status,
        "mutating": False,
        "allowed_intents": ["report"],
    },
    "get_department_info": {
        "name": "get_department_info",
        "description": "查询科室简介、位置和联系电话，用于科室推荐或就诊指引。",
        "parameters": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "科室关键词，如 内科、儿科"},
                "department_name": {"type": "string", "description": "科室全名，可选"},
            },
        },
        "handler": svc.get_department_info,
        "mutating": False,
        "allowed_intents": ["department"],
    },
    "get_charge_detail": {
        "name": "get_charge_detail",
        "description": "查询当前患者本次就诊的费用明细、医保支付与自费金额。",
        "parameters": _patient_schema({"visit_no": {"type": "string", "description": "就诊流水号，可选"}}),
        "handler": svc.get_charge_detail,
        "mutating": False,
        "allowed_intents": ["fee"],
    },
    "create_ticket": {
        "name": "create_ticket",
        "description": "创建患者服务工单并分配处理部门，用于投诉、建议或需要人工跟进的问题。",
        "parameters": _patient_schema(
            {
                "title": {"type": "string", "description": "工单标题，不超过 60 字"},
                "content": {"type": "string", "description": "患者问题描述与已核实信息"},
                "category": {"type": "string", "description": "工单类别，如 投诉建议、预约挂号"},
                "priority": {"type": "string", "enum": ["low", "normal", "high", "urgent"]},
                "department": {"type": "string", "description": "处理部门，可选"},
                "need_human": {"type": "boolean", "description": "是否需要人工介入"},
            },
            ["patient_id", "title", "content", "category"],
        ),
        "handler": svc.create_ticket,
        "mutating": True,
        "allowed_intents": ["complaint", "fee"],
    },
    "get_ticket_status": {
        "name": "get_ticket_status",
        "description": "查询当前患者某个工单的处理状态与流转记录。",
        "parameters": _patient_schema(
            {"ticket_no": {"type": "string", "description": "工单编号，如 TK202611180001"}},
            ["patient_id", "ticket_no"],
        ),
        "handler": svc.get_ticket_status,
        "mutating": False,
        "allowed_intents": ["other", "complaint"],
    },
    "assign_ticket": {
        "name": "assign_ticket",
        "description": "将工单分配给指定处理部门。仅内部流程使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "ticket_no": {"type": "string"},
                "department": {"type": "string"},
                "operator": {"type": "string"},
            },
            "required": ["ticket_no", "department"],
        },
        "handler": svc.assign_ticket,
        "mutating": True,
        "allowed_intents": [],
    },
    "add_ticket_comment": {
        "name": "add_ticket_comment",
        "description": "向工单追加一条处理记录。仅内部流程使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "ticket_no": {"type": "string"},
                "content": {"type": "string"},
                "operator": {"type": "string"},
                "action": {"type": "string"},
            },
            "required": ["ticket_no", "content"],
        },
        "handler": svc.add_ticket_comment,
        "mutating": True,
        "allowed_intents": [],
    },
}


def tool_schemas(allowed: list[str] | None = None) -> list[dict]:
    """给 LLM 的工具描述（不含内部执行函数）。"""
    names = allowed or [n for n, t in TOOLS.items() if not t["mutating"]]
    return [
        {"name": n, "description": TOOLS[n]["description"], "parameters": TOOLS[n]["parameters"]}
        for n in names
        if n in TOOLS
    ]


def get_handler(name: str) -> Callable | None:
    tool = TOOLS.get(name)
    return tool["handler"] if tool else None

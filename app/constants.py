"""业务常量：意图、分类、优先级、状态映射。"""
from __future__ import annotations

from typing import Dict

INTENT_MEDICAL_GUIDE = "medical_guide"
INTENT_INSURANCE = "insurance"
INTENT_DEPARTMENT = "department"
INTENT_APPOINTMENT = "appointment"
INTENT_APPOINTMENT_CANCEL = "appointment_cancel"
INTENT_REPORT = "report"
INTENT_FEE = "fee"
INTENT_COMPLAINT = "complaint"
INTENT_OTHER = "other"
INTENT_CONFIRM_PENDING = "confirm_pending"

INTENTS: Dict[str, dict] = {
    INTENT_MEDICAL_GUIDE: {"label": "就诊指南", "category": "就诊咨询", "department": "门诊服务中心"},
    INTENT_INSURANCE: {"label": "医保咨询", "category": "医保咨询", "department": "医保办公室"},
    INTENT_DEPARTMENT: {"label": "科室咨询", "category": "科室咨询", "department": "门诊服务中心"},
    INTENT_APPOINTMENT: {"label": "预约查询", "category": "预约挂号", "department": "门诊服务中心"},
    INTENT_APPOINTMENT_CANCEL: {"label": "预约取消", "category": "预约挂号", "department": "门诊服务中心"},
    INTENT_REPORT: {"label": "检查报告", "category": "检查报告", "department": "检验科"},
    INTENT_FEE: {"label": "费用咨询", "category": "费用问题", "department": "财务收费处"},
    INTENT_COMPLAINT: {"label": "投诉建议", "category": "投诉建议", "department": "门诊服务中心"},
    INTENT_OTHER: {"label": "其他咨询", "category": "综合咨询", "department": "门诊服务中心"},
    INTENT_CONFIRM_PENDING: {"label": "操作确认", "category": "预约挂号", "department": "门诊服务中心"},
}

PRIORITY_LABELS = {"low": "低", "normal": "普通", "high": "较高", "urgent": "紧急"}

TICKET_STATUS_LABELS = {
    "pending": "待受理",
    "processing": "处理中",
    "waiting_human": "待人工处理",
    "resolved": "已解决",
    "closed": "已关闭",
    "cancelled": "已取消",
}

REPORT_STATUS_LABELS = {
    "processing": "检测处理中",
    "ready": "报告已出具",
    "delivered": "已领取",
}

APPOINTMENT_STATUS_LABELS = {"booked": "已预约", "cancelled": "已取消", "completed": "已完成"}

# 触发紧急安全通道的关键词（命中即提示拨打 120，不进入普通工单流程）
EMERGENCY_KEYWORDS = [
    "胸痛", "胸口疼", "呼吸困难", "喘不上气", "大出血", "昏迷", "晕倒", "抽搐",
    "自杀", "轻生", "农药", "中毒", "车祸", "大咯血", "剧烈头痛伴呕吐", "卒中", "半边瘫",
    "高热惊厥", "窒息", "休克",
]

# 敏感/越权请求：引导走人工核验
PRIVACY_KEYWORDS = ["他人报告", "别人的报告", "帮我查一下我老婆", "帮我查一下我丈夫", "身份证号", "病历号"]

CONFIRM_WORDS = ["确认", "确定", "是的", "是", "好的", "可以", "同意", "取消吧", "帮我取消", "yes", "ok"]
DENY_WORDS = ["不取消", "算了", "先不", "不用了", "不要取消", "我再想想", "否", "no"]

BOUNDARY_NOTE = "以上内容依据医院公开制度与指南整理，仅作就医指引，不构成诊断或治疗建议。"

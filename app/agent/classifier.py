"""关键词规则分类器：无 LLM Key 时的兜底，也用于 FAQ 缓存的快速判定。"""
from __future__ import annotations

from app.constants import (
    INTENT_APPOINTMENT,
    INTENT_APPOINTMENT_CANCEL,
    INTENT_COMPLAINT,
    INTENT_DEPARTMENT,
    INTENT_FEE,
    INTENT_INSURANCE,
    INTENT_MEDICAL_GUIDE,
    INTENT_OTHER,
    INTENT_REPORT,
    INTENTS,
)

_COMPLAINT_WORDS = ["投诉", "白跑", "态度", "不满意", "举报", "没人管", "没有提前通知", "没通知", "临时取消", "爽约"]
_CANCEL_WORDS = ["取消", "退号", "不去了", "改约", "退掉"]
_APPOINTMENT_WORDS = ["预约", "挂号", "号源", "号", "医生时间", "排班", "签到", "候诊"]
_REPORT_WORDS = ["报告", "化验", "检验单", "检查结果", "结果出来", "ct", "核磁", "b超", "病理"]
_FEE_WORDS = ["费用", "收费", "太贵", "多少钱", "明细", "发票", "退费", "乱收费", "重复收费"]
_INSURANCE_WORDS = ["医保", "报销", "社保", "统筹", "自费", "异地就医", "慢特病"]
_GUIDE_WORDS = ["就诊", "准备", "带什么", "第一次", "流程", "几点", "门诊时间", "材料", "挂号须知", "怎么走"]
_DEPARTMENT_WORDS = ["哪个科", "挂什么科", "什么科室", "科室", "头痛", "肚子疼", "腹痛", "胸痛挂", "看什么科"]

INTENT_KEYWORDS = {
    INTENT_COMPLAINT: _COMPLAINT_WORDS,
    INTENT_APPOINTMENT_CANCEL: _CANCEL_WORDS,
    INTENT_REPORT: _REPORT_WORDS,
    INTENT_FEE: _FEE_WORDS,
    INTENT_INSURANCE: _INSURANCE_WORDS,
    INTENT_DEPARTMENT: _DEPARTMENT_WORDS,
    INTENT_APPOINTMENT: _APPOINTMENT_WORDS,
    INTENT_MEDICAL_GUIDE: _GUIDE_WORDS,
}

RULE_FAQ_INTENTS = {INTENT_MEDICAL_GUIDE, INTENT_INSURANCE, INTENT_DEPARTMENT, INTENT_OTHER}


def classify_by_rules(question: str) -> tuple[str, str]:
    """返回 (intent, priority)。"""
    q = question.lower()
    if any(w in q for w in _COMPLAINT_WORDS):
        return INTENT_COMPLAINT, "high"

    if any(w in q for w in _CANCEL_WORDS) and any(w in q for w in _APPOINTMENT_WORDS):
        return INTENT_APPOINTMENT_CANCEL, "normal"

    for intent in (INTENT_REPORT, INTENT_FEE, INTENT_INSURANCE, INTENT_DEPARTMENT):
        if any(w in q for w in INTENT_KEYWORDS[intent]):
            return intent, "normal"

    if any(w in q for w in _APPOINTMENT_WORDS):
        return INTENT_APPOINTMENT, "normal"
    if any(w in q for w in _GUIDE_WORDS):
        return INTENT_MEDICAL_GUIDE, "normal"
    return INTENT_OTHER, "normal"


def resolve_meta(intent: str) -> dict:
    return INTENTS.get(intent, INTENTS[INTENT_OTHER])

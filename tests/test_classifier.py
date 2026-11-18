"""意图分类规则测试。"""
from app.agent.classifier import classify_by_rules


def test_cancel_appointment():
    intent, _ = classify_by_rules("我预约的明天下午的号怎么取消？")
    assert intent == "appointment_cancel"


def test_report_status():
    intent, _ = classify_by_rules("我的检查报告什么时候出来？")
    assert intent == "report"


def test_insurance():
    intent, _ = classify_by_rules("门诊检查可以报销吗？")
    assert intent == "insurance"


def test_complaint_priority():
    intent, priority = classify_by_rules("医生预约时间变更，没有提前通知我，白跑了一趟")
    assert intent == "complaint"
    assert priority == "high"


def test_medical_guide():
    intent, _ = classify_by_rules("第一次去医院看病需要带什么材料？")
    assert intent == "medical_guide"

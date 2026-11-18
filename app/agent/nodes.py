"""LangGraph 节点实现：分类、安全检查、路由、RAG、工具调用、工单、确认、复核。"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from app.agent.llm import llm_service
from app.agent.state import TicketState
from app.agent.tools import gateway
from app.config import settings
from app.constants import (
    BOUNDARY_NOTE,
    CONFIRM_WORDS,
    DENY_WORDS,
    EMERGENCY_KEYWORDS,
    INTENT_APPOINTMENT,
    INTENT_APPOINTMENT_CANCEL,
    INTENT_COMPLAINT,
    INTENT_CONFIRM_PENDING,
    INTENT_DEPARTMENT,
    INTENT_FEE,
    INTENT_INSURANCE,
    INTENT_MEDICAL_GUIDE,
    INTENT_OTHER,
    INTENT_REPORT,
    INTENTS,
    PRIORITY_LABELS,
    PRIVACY_KEYWORDS,
    TICKET_STATUS_LABELS,
)
from app.rag.pipeline import retriever
from app.utils import mask_sensitive

logger = logging.getLogger(__name__)

HOTLINE = "0571-88000000"
TICKET_RE = re.compile(r"TK\d{6,}")

SYMPTOM_DEPARTMENTS: Dict[str, str] = {
    "头痛": "神经内科 / 内科",
    "头晕": "神经内科 / 内科",
    "胸闷": "心血管内科",
    "心悸": "心血管内科",
    "腹痛": "消化内科 / 普外科",
    "肚子疼": "消化内科 / 普外科",
    "咳嗽": "呼吸内科",
    "发热": "发热门诊 / 内科",
    "皮疹": "皮肤科",
    "牙痛": "口腔科",
    "眼睛": "眼科",
    "耳鸣": "耳鼻喉科",
    "腰痛": "骨科",
    "关节": "骨科",
}


def _trace(state: TicketState, message: str) -> List[str]:
    return list(state.get("trace") or []) + [message]


def _history_text(state: TicketState, limit: int = 6) -> str:
    rows = (state.get("history") or [])[-limit:]
    return "\n".join(f"{'患者' if row.get('role') == 'user' else '客服'}：{row.get('content', '')}" for row in rows)


def _meta(intent: str) -> dict:
    return INTENTS.get(intent, INTENTS[INTENT_OTHER])


def _is_confirm(question: str) -> bool:
    q = question.strip().lower()
    if any(w in q for w in DENY_WORDS):
        return False
    if len(q) <= 14 and any(w in q for w in CONFIRM_WORDS):
        return True
    return any(w in q for w in ["确认取消", "确定取消", "取消预约吧", "帮我取消吧"])


def _is_deny(question: str) -> bool:
    q = question.strip().lower()
    return any(w in q for w in DENY_WORDS)


async def classify_node(state: TicketState) -> dict:
    """意图识别：优先处理「待确认动作」的上下文，再交给 LLM/规则分类。"""
    trace = list(state.get("trace") or [])
    question = state["question"]
    pending = state.get("pending_action")

    if pending:
        if _is_deny(question):
            trace.append("classify：患者放弃待确认操作")
            return {
                "intent": INTENT_OTHER,
                "category": "预约挂号",
                "department": "门诊服务中心",
                "priority": "normal",
                "direct_reply": True,
                "pending_action": None,
                "need_human": False,
                "emergency": False,
                "answer": "好的，本次操作已取消，您的预约保持不变。如有其他需要，请随时告诉我。",
                "trace": trace,
            }
        if _is_confirm(question):
            trace.append("classify：检测到患者明确确认，进入操作执行节点")
            return {
                "intent": INTENT_CONFIRM_PENDING,
                "category": "预约挂号",
                "department": "门诊服务中心",
                "priority": "normal",
                "direct_reply": False,
                "trace": trace,
            }
        trace.append("classify：患者切换了话题，清除待确认动作")

    result = await llm_service.classify(question, _history_text(state))
    meta = _meta(result.intent)
    trace.append(
        f"classify：识别意图「{meta['label']}」，优先级={PRIORITY_LABELS.get(result.priority, result.priority)}"
    )
    return {
        "intent": result.intent,
        "category": result.category or meta["category"],
        "department": result.department or meta["department"],
        "priority": result.priority,
        "reason": result.reason,
        "pending_action": None if pending else state.get("pending_action"),
        "direct_reply": False,
        "emergency": False,
        "need_human": False,
        "trace": trace,
    }


async def safety_node(state: TicketState) -> dict:
    """安全检查：急危重症优先提示急救；越权/隐私请求引导人工核验。"""
    trace = list(state.get("trace") or [])
    question = state["question"]

    if any(word in question for word in EMERGENCY_KEYWORDS):
        trace.append("safety：命中急危重症关键词，转急救提示（不进入普通工单流程）")
        return {
            "emergency": True,
            "need_human": True,
            "direct_reply": True,
            "answer": (
                "【紧急提示】您描述的情况可能属于急危重症，请立即拨打 120 或尽快前往最近医院急诊科就诊，"
                "不要等待线上客服回复。若您或身边的人出现意识不清、呼吸困难、持续胸痛、大出血等情况，请立刻寻求现场急救帮助。"
            ),
            "trace": trace,
        }

    if any(word in question for word in PRIVACY_KEYWORDS):
        trace.append("safety：识别到隐私/越权查询请求，拒绝并提示人工核验")
        return {
            "need_human": True,
            "direct_reply": True,
            "answer": (
                "为保护患者隐私，我无法查询或提供他人病历、报告等信息。"
                "如需代家人查询，请携带患者签署的授权委托书及双方身份证件，到门诊服务中心窗口办理。"
            ),
            "trace": trace,
        }

    trace.append("safety：未发现紧急或越权风险")
    return {"emergency": False, "direct_reply": False, "trace": trace}


def route_node(state: TicketState) -> str:
    """条件路由：只决定分支，不执行业务逻辑。"""
    if state.get("emergency") or state.get("direct_reply"):
        return "review"
    intent = state.get("intent", INTENT_OTHER)
    if intent == INTENT_CONFIRM_PENDING:
        return "confirm"
    if intent == INTENT_COMPLAINT:
        return "ticket"
    if intent in {
        INTENT_APPOINTMENT,
        INTENT_APPOINTMENT_CANCEL,
        INTENT_REPORT,
        INTENT_FEE,
        INTENT_DEPARTMENT,
    }:
        return "tools"
    if TICKET_RE.search(state.get("question", "")):
        return "tools"
    return "rag"


def _extractive_answer(chunks) -> str:
    parts = []
    for c in chunks[:3]:
        content = re.sub(r"\n{2,}", "\n", c.chunk.content).strip()
        if len(content) > 420:
            content = content[:420] + "…"
        parts.append(f"【{c.chunk.title} · {c.chunk.section}】\n{content}")
    return "\n\n".join(parts)


async def rag_node(state: TicketState) -> dict:
    """RAG 分支：混合检索 → 生成带来源的回答；无依据时明确拒答并转人工。"""
    trace = list(state.get("trace") or [])
    question = state["question"]
    try:
        chunks = await retriever.retrieve(question)
    except Exception as exc:
        logger.exception("RAG 检索失败")
        chunks = []
        trace.append(f"rag：检索异常（{exc}）")

    sources = [c.to_source() for c in chunks]
    context = retriever.build_context(chunks)

    if not chunks:
        trace.append("rag：未检索到可靠依据，禁止编造并提示人工客服")
        return {
            "rag_context": "",
            "sources": [],
            "need_human": True,
            "answer": (
                "暂未在医院知识库中检索到与您问题直接相关的依据。"
                f"为避免提供不准确的信息，建议您联系患者服务中心 {HOTLINE} 或转人工客服进一步确认。"
            ),
            "trace": trace,
        }

    trace.append(f"rag：混合检索命中 {len(chunks)} 条依据（{'Milvus+BM25' if retriever._milvus.searchable else 'BM25'}）")
    answer = await llm_service.answer(question, context=context, history=_history_text(state))
    if answer:
        trace.append("rag：由大模型基于检索结果生成回答")
    else:
        answer = _extractive_answer(chunks)
        trace.append("rag：离线模式，按检索结果模板化回答")

    return {
        "rag_context": context,
        "sources": sources,
        "need_human": False,
        "answer": answer,
        "trace": trace,
    }


def _render_tool_answer(tool_name: str, data: dict, question: str = "") -> str:
    """离线/无 Key 时的工具结果模板。"""
    if not data.get("ok"):
        return f"本次查询未完成：{data.get('error', '业务系统暂不可用')}。可联系患者服务中心 {HOTLINE}。"

    if tool_name == "get_appointment":
        rows = data.get("appointments") or []
        if not rows:
            return "您当前没有有效的预约记录。如需挂号，可通过医院公众号或门诊服务中心办理。"
        lines = ["为您查询到以下预约记录："]
        for a in rows:
            lines.append(
                f"· {a['appointment_time']}　{a['department']}　{a['doctor_name']}　"
                f"预约号 {a['appointment_no']}　状态：{a['status_label']}"
            )
        lines.append(f"如需取消，请提前 {settings.cancel_min_hours} 小时办理。")
        return "\n".join(lines)

    if tool_name == "get_report_status":
        lines = ["为您查询到以下报告状态："]
        for r in data.get("reports", []):
            lines.append(f"· {r['item_name']}（{r['report_no']}）：{r['status_label']}，更新时间 {r['updated_at']}")
        lines.append(data.get("notice", "报告解读请咨询开单医生。"))
        return "\n".join(lines)

    if tool_name == "get_department_info":
        rows = data.get("departments") or []
        lines = ["科室信息如下："]
        for d in rows[:3]:
            lines.append(f"· {d['name']}：{d['location']}，电话 {d['phone']}。{d['description']}")
        suggestion = next((v for k, v in SYMPTOM_DEPARTMENTS.items() if k in question), None)
        if suggestion:
            lines.append(f"根据您描述的症状，可优先考虑：{suggestion}。最终请以分诊台意见为准。")
        return "\n".join(lines)

    if tool_name == "get_charge_detail":
        lines = [f"本次就诊（流水号 {data.get('visit_no')}）费用明细："]
        for item in data.get("items", [])[:8]:
            lines.append(
                f"· {item['item_name']}（{item['category']}）：{item['amount']:.2f} 元，"
                f"医保支付 {item['insurance_amount']:.2f} 元，自费 {item['self_pay']:.2f} 元"
            )
        lines.append(
            f"合计 {data.get('total_amount', 0):.2f} 元，医保支付 {data.get('insurance_amount', 0):.2f} 元，"
            f"个人自费 {data.get('self_pay_amount', 0):.2f} 元。"
        )
        return "\n".join(lines)

    if tool_name == "get_ticket_status":
        lines = [
            f"工单 {data.get('ticket_no')}：{data.get('title')}",
            f"当前状态：{data.get('status_label')}，处理部门：{data.get('department')}，更新时间：{data.get('updated_at')}",
        ]
        for log in (data.get("logs") or [])[-3:]:
            lines.append(f"· {log['created_at']}　{log['operator']}：{log['content']}")
        return "\n".join(lines)

    return json.dumps(data, ensure_ascii=False)


async def _run_tool(
    name: str,
    arguments: dict,
    state: TicketState,
    trace: List[str],
) -> tuple[dict, str]:
    data, transport = await gateway.call(name, arguments)
    trace.append(f"tools：调用 {name}（transport={transport}）")
    return data, transport


async def tools_node(state: TicketState) -> dict:
    """MCP 工具分支：预约、报告、费用、科室、工单状态查询，必要时自动建单。"""
    trace = list(state.get("trace") or [])
    intent = state.get("intent", INTENT_OTHER)
    patient_id = int(state["patient_id"])
    question = state["question"]

    tool_name: Optional[str] = None
    arguments: dict[str, Any] = {"patient_id": patient_id}
    tool_result: Optional[dict] = None
    transport = "none"
    ticket_id: Optional[str] = None
    ticket_status: Optional[str] = None
    need_human = False

    try:
        if intent == INTENT_APPOINTMENT_CANCEL:
            data, transport = await _run_tool("get_appointment", {"patient_id": patient_id}, state, trace)
            tool_name, tool_result = "get_appointment", data
            rows = data.get("appointments") or []
            if not data.get("ok") or not rows:
                answer = _render_tool_answer("get_appointment", data, question)
                return {"tool_name": tool_name, "tool_result": data, "tool_transport": transport,
                        "answer": answer, "need_human": True, "trace": trace}
            first = rows[0]
            pending = {
                "name": "cancel_appointment",
                "arguments": {"patient_id": patient_id, "appointment_id": first["appointment_id"]},
                "appointment_no": first["appointment_no"],
                "summary": f"{first['appointment_time']} {first['department']} {first['doctor_name']}",
            }
            extra = ""
            if len(rows) > 1:
                extra = f"\n您当前共有 {len(rows)} 个有效预约，将优先处理最近的一个。"
            answer = (
                f"已为您核实到预约：{first['appointment_time']}　{first['department']}　"
                f"{first['doctor_name']}（预约号 {first['appointment_no']}）。{extra}\n\n"
                f"按医院规定，线上取消需在就诊前 {settings.cancel_min_hours} 小时办理"
                f"（取消截止：{first['cancel_deadline']}）。\n"
                "请回复「确认取消」完成操作，或回复「不取消」保留预约。"
            )
            trace.append("tools：查询预约成功，等待患者二次确认后执行取消")
            return {
                "tool_name": tool_name,
                "tool_result": data,
                "tool_transport": transport,
                "pending_action": pending,
                "answer": answer,
                "need_human": False,
                "ticket_id": None,
                "ticket_status": None,
                "trace": trace,
            }

        if intent == INTENT_REPORT:
            tool_name = "get_report_status"
        elif intent == INTENT_FEE:
            tool_name = "get_charge_detail"
        elif intent == INTENT_DEPARTMENT:
            tool_name = "get_department_info"
            arguments = {}
            known = [d for d in ["内科", "外科", "儿科", "骨科", "皮肤科", "眼科", "口腔科", "妇产科", "耳鼻喉科"] if d in question]
            if known:
                arguments["keyword"] = known[0]
        elif intent == INTENT_APPOINTMENT:
            tool_name = "get_appointment"
        elif TICKET_RE.search(question):
            tool_name = "get_ticket_status"
            arguments["ticket_no"] = TICKET_RE.search(question).group(0)  # type: ignore[union-attr]
        else:
            tool_name = "get_department_info"

        # 复用 LLM 做工具选择（仅限只读工具），参数仍由后端注入 patient_id
        from app.mcp.registry import tool_schemas

        allowed = [tool_name] if tool_name else []
        picked = await llm_service.select_tool(question, tool_schemas(allowed), patient_id)
        if picked:
            tool_name = picked["name"]
            for key, value in picked["arguments"].items():
                if key != "patient_id":
                    arguments[key] = value
            trace.append(f"tools：LLM 选择工具 {tool_name}")
        else:
            trace.append(f"tools：按意图规则选择工具 {tool_name}")

        data, transport = await _run_tool(tool_name, arguments, state, trace)
        tool_result = data

        if tool_name == "get_charge_detail" and data.get("ok"):
            total = float(data.get("total_amount") or 0)
            dispute = any(w in question for w in ["为什么", "太高", "太贵", "不合理", "重复", "乱收", "投诉", "退费"])
            if dispute or total >= settings.fee_dispute_amount:
                ticket_title = await llm_service.summarize(f"费用疑问：{question}", 40)
                created, t2 = await _run_tool(
                    "create_ticket",
                    {
                        "patient_id": patient_id,
                        "title": ticket_title,
                        "content": mask_sensitive(question),
                        "category": "费用问题",
                        "priority": "high",
                        "department": "财务收费处",
                        "need_human": True,
                    },
                    state,
                    trace,
                )
                if created.get("ok"):
                    ticket_id = created["ticket_no"]
                    ticket_status = created["status"]
                    trace.append(f"ticket：已创建费用复核工单 {ticket_id}（transport={t2}）")
                need_human = True

        if not data.get("ok"):
            need_human = bool(data.get("need_human")) or need_human

        answer = ""
        if data.get("ok"):
            answer = await llm_service.answer(
                question,
                tool_result=json.dumps(data, ensure_ascii=False),
                history=_history_text(state),
            )
        if not answer:
            answer = _render_tool_answer(tool_name, data, question)
        if ticket_id:
            answer += (
                f"\n\n已为您登记费用复核工单 {ticket_id}，当前状态："
                f"{TICKET_STATUS_LABELS.get(ticket_status or '', '待人工处理')}，"
                "财务收费处将在 3 个工作日内核对并反馈。"
            )

        return {
            "tool_name": tool_name,
            "tool_result": tool_result,
            "tool_transport": transport,
            "ticket_id": ticket_id,
            "ticket_status": ticket_status,
            "need_human": need_human,
            "answer": answer,
            "sources": [],
            "trace": trace,
        }
    except Exception as exc:
        logger.exception("工具节点异常")
        return {
            "tool_name": tool_name,
            "tool_result": tool_result,
            "tool_transport": transport,
            "need_human": True,
            "error": str(exc),
            "answer": f"业务查询暂时不可用，已记录该问题。您可稍后重试或联系患者服务中心 {HOTLINE}。",
            "trace": trace + [f"tools：执行异常 {exc}"],
        }


async def ticket_node(state: TicketState) -> dict:
    """工单分支：核实业务数据 + 检索制度依据 → 创建工单 → 分配部门 → 生成回复。"""
    trace = list(state.get("trace") or [])
    patient_id = int(state["patient_id"])
    question = state["question"]
    sources: List[dict] = []
    context = ""
    evidence: List[str] = []

    try:
        chunks = await retriever.retrieve(question)
        if chunks:
            context = retriever.build_context(chunks)
            sources = [c.to_source() for c in chunks]
            trace.append(f"ticket：检索到 {len(chunks)} 条制度依据")
    except Exception as exc:
        logger.warning("工单检索制度依据失败: %s", exc)

    if any(word in question for word in ["预约", "挂号", "医生", "停诊", "号"]):
        appt, transport = await _run_tool("get_appointment", {"patient_id": patient_id}, state, trace)
        for a in (appt.get("appointments") or [])[:3]:
            evidence.append(f"{a['appointment_time']} {a['department']} {a['doctor_name']}（{a['appointment_no']}，{a['status_label']}）")
        if evidence:
            trace.append("ticket：已核实预约记录，作为工单佐证")

    title = await llm_service.summarize(question, 40)
    content = question + ("\n\n[患者当前有效预约（供核实）]\n" + "；".join(evidence) if evidence else "")

    created, transport = await _run_tool(
        "create_ticket",
        {
            "patient_id": patient_id,
            "title": title,
            "content": mask_sensitive(content),
            "category": state.get("category", "投诉建议"),
            "priority": state.get("priority", "high"),
            "department": state.get("department") or "门诊服务中心",
            "need_human": True,
        },
        state,
        trace,
    )

    if not created.get("ok"):
        return {
            "need_human": True,
            "error": created.get("error"),
            "sources": sources,
            "answer": f"工单创建未成功：{created.get('error', '系统繁忙')}。请稍后重试或联系患者服务中心 {HOTLINE}。",
            "trace": trace,
        }

    ticket_no = created["ticket_no"]
    department = created["department"]
    await _run_tool("assign_ticket", {"ticket_no": ticket_no, "department": department}, state, trace)
    if sources:
        await _run_tool(
            "add_ticket_comment",
            {
                "ticket_no": ticket_no,
                "content": "制度依据：" + "；".join(f"《{s['title']}》·{s['section']}" for s in sources[:3]),
                "operator": "智能客服 Agent",
                "action": "reference",
            },
            state,
            trace,
        )

    basis = ""
    if sources:
        basis = "\n\n处理依据：" + "；".join(f"《{s['title']}》·{s['section']}" for s in sources[:2])

    answer = await llm_service.answer(
        question,
        context=context,
        tool_result=json.dumps(created, ensure_ascii=False),
        history=_history_text(state),
    )
    if not answer:
        answer = (
            f"您的反馈已成功登记，工单编号：{ticket_no}。\n"
            f"· 工单类型：{created['category']}\n"
            f"· 处理部门：{department}\n"
            f"· 当前状态：{TICKET_STATUS_LABELS.get(created['status'], created['status'])}\n"
            f"· 处理时限：一般投诉 3 个工作日内答复，复杂问题 7 个工作日内答复。{basis}\n\n"
            "您可以在「我的工单」中查看处理进度，工作人员核实后会与您联系。"
        )
    else:
        answer += f"\n\n工单编号：{ticket_no}，已转交{department}处理，可在「我的工单」查看进度。"

    return {
        "ticket_id": ticket_no,
        "ticket_status": created["status"],
        "need_human": True,
        "rag_context": context,
        "sources": sources,
        "answer": answer,
        "trace": trace,
    }


async def confirm_node(state: TicketState) -> dict:
    """操作确认节点：仅在患者明确确认后执行取消预约等有副作用的操作。"""
    trace = list(state.get("trace") or [])
    pending = state.get("pending_action") or {}
    name = pending.get("name")
    arguments = pending.get("arguments") or {}

    if name != "cancel_appointment" or not arguments:
        trace.append("confirm：没有可执行的待确认操作")
        return {
            "pending_action": None,
            "answer": "当前没有待确认的操作。如需取消预约，请告诉我预约的科室或时间。",
            "trace": trace,
        }

    data, transport = await _run_tool(name, arguments, state, trace)
    if data.get("ok"):
        trace.append("confirm：患者已确认，预约取消成功")
        answer = (
            f"已为您取消预约：{data['appointment_time']}　{data['department']}　{data['doctor_name']}"
            f"（预约号 {data['appointment_no']}）。{data['message']}\n"
            "如需重新预约，可通过医院公众号或门诊服务中心办理。"
        )
        need_human = False
    else:
        trace.append(f"confirm：操作未完成（{data.get('error')}）")
        answer = (
            f"本次取消未完成：{data.get('error', '业务系统暂不可用')}。\n"
            f"您可联系患者服务中心 {HOTLINE} 协助处理。"
        )
        need_human = bool(data.get("need_human")) or True

    return {
        "pending_action": None,
        "tool_result": data,
        "tool_name": name,
        "tool_transport": transport,
        "need_human": need_human,
        "answer": answer,
        "trace": trace,
    }


async def review_node(state: TicketState) -> dict:
    """结果复核：兜底回答、补充就医边界声明、标记转人工。"""
    trace = list(state.get("trace") or [])
    answer = (state.get("answer") or "").strip()
    need_human = bool(state.get("need_human"))
    intent = state.get("intent", INTENT_OTHER)

    if not answer:
        answer = f"抱歉，本次服务未能完成处理。请稍后重试或联系患者服务中心 {HOTLINE}。"
        need_human = True

    if intent in {INTENT_MEDICAL_GUIDE, INTENT_INSURANCE, INTENT_DEPARTMENT} and not state.get("emergency"):
        if BOUNDARY_NOTE not in answer:
            answer = f"{answer}\n\n{BOUNDARY_NOTE}"

    if state.get("error"):
        need_human = True

    if state.get("ticket_id"):
        trace.append(f"review：工单 {state['ticket_id']} 已创建，状态={state.get('ticket_status')}")
    trace.append("review：完成结果复核" + ("，已标记转人工" if need_human else ""))

    return {"answer": answer, "need_human": need_human, "trace": trace}

"""LLM 封装：意图分类、工具选择、答案生成，均带离线降级。"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.agent.classifier import classify_by_rules, resolve_meta
from app.config import settings
from app.constants import INTENTS, PRIORITY_LABELS

logger = logging.getLogger(__name__)


class Classification(BaseModel):
    intent: str = Field(description="意图，必须是给定枚举之一")
    category: str = Field(description="工单类别中文名")
    department: str = Field(description="建议处理部门")
    priority: str = Field(description="优先级：low/normal/high/urgent")
    reason: str = Field(default="", description="分类依据，20 字以内")


CLASSIFY_PROMPT = """你是医院患者服务中心的意图识别模块。请判断患者问题的意图。

可选意图：
- medical_guide：就诊指南（流程、材料、时间、注意事项）
- insurance：医保政策（报销、异地就医、慢特病）
- department：科室选择（头疼挂什么科、科室位置）
- appointment：预约/挂号查询（查询、改约咨询）
- appointment_cancel：取消预约
- report：检查报告状态查询
- fee：费用查询与费用争议
- complaint：投诉建议（服务态度、停诊未通知、爽约、重复收费）
- other：其他

规则：
1. 只说「想取消预约」属于 appointment_cancel；只是查询预约信息属于 appointment。
2. 涉及投诉、追责、要求处理的归为 complaint，优先级至少 high。
3. 问题中出现急危重症描述时，优先级 urgent。
4. 只输出 JSON，不要编造。

对话历史：
{history}

患者问题：{question}
"""

ANSWER_PROMPT = """你是「仁心医院」患者服务中心的智能客服。请严格依据给定资料回答患者问题。

硬性要求：
1. 只能使用【知识库资料】和【业务系统结果】中的信息，不得编造医院政策、金额、时间、报告结论。
2. 资料不足或不确定时，明确说明「暂未查询到相关依据」，并建议联系患者服务中心 0571-88000000 或转人工，不得猜测。
3. 不提供疾病诊断、处方、用药剂量或治疗方案；涉及急危重症时提醒立即拨打 120。
4. 回答使用简洁的中文，分点说明，必要时引用来源，格式如「（来源：就诊指南·首次就诊需要准备的材料）」。
5. 不要暴露内部字段名、SQL、工具名，不要输出 JSON。

【知识库资料】
{context}

【业务系统结果】
{tool_result}

【对话历史摘要】
{history}

患者问题：{question}
"""

TOOL_PROMPT = """你是医院业务工具调用模块。根据患者问题，从允许的工具中选择一个，并给出调用参数。

允许的工具（JSON Schema 描述）：
{tools}

规则：
- 只能选择列表中的工具，参数必须来自患者问题或已知的 patient_id。
- 不涉及具体业务数据查询时返回 {{"name": null}}。
- 只输出 JSON，例如 {{"name": "get_report_status", "arguments": {{"patient_id": 1}}}}。

患者问题：{question}
"""


def _extract_json(text: str) -> Optional[dict]:
    text = text.strip()
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


class LLMService:
    def __init__(self) -> None:
        self._chat = None

    @property
    def available(self) -> bool:
        return settings.llm_enabled

    def _client(self):
        if self._chat is None:
            from langchain_openai import ChatOpenAI

            kwargs: Dict[str, Any] = {
                "model": settings.llm_model,
                "api_key": settings.llm_api_key,
                "temperature": settings.llm_temperature,
                "timeout": settings.llm_timeout,
                "max_retries": 2,
            }
            if settings.llm_base_url:
                kwargs["base_url"] = settings.llm_base_url
            self._chat = ChatOpenAI(**kwargs)
        return self._chat

    async def classify(self, question: str, history: str = "") -> Classification:
        fallback_intent, fallback_priority = classify_by_rules(question)
        fallback_meta = resolve_meta(fallback_intent)
        fallback = Classification(
            intent=fallback_intent,
            category=fallback_meta["category"],
            department=fallback_meta["department"],
            priority=fallback_priority,
            reason="规则分类（LLM 不可用）",
        )
        if not self.available:
            return fallback

        try:
            llm = self._client().with_structured_output(Classification, method="function_calling")
            result: Classification = await llm.ainvoke(
                CLASSIFY_PROMPT.format(history=history[-1500:] or "无", question=question)
            )
            if result.intent not in INTENTS:
                result.intent = fallback_intent
            meta = resolve_meta(result.intent)
            if result.category not in {m["category"] for m in INTENTS.values()}:
                result.category = meta["category"]
            if result.priority not in PRIORITY_LABELS:
                result.priority = fallback_priority
            if not result.department:
                result.department = meta["department"]
            return result
        except Exception as exc:
            logger.warning("LLM 分类失败，使用规则兜底: %s", exc)
            return fallback

    async def select_tool(self, question: str, tools: List[dict], patient_id: int) -> Optional[dict]:
        if not self.available or not tools:
            return None
        try:
            prompt = TOOL_PROMPT.format(
                tools=json.dumps(tools, ensure_ascii=False, indent=2), question=question
            )
            resp = await self._client().ainvoke(prompt)
            payload = _extract_json(resp.content if isinstance(resp.content, str) else str(resp.content))
            if not payload or not payload.get("name"):
                return None
            allowed = {t["name"] for t in tools}
            if payload["name"] not in allowed:
                return None
            schema_props = {
                t["name"]: set((t.get("parameters") or {}).get("properties", {})) for t in tools
            }
            props = schema_props[payload["name"]]
            raw_args = payload.get("arguments") or {}
            if not isinstance(raw_args, dict):
                return None
            # 只接受工具 Schema 中声明的参数；patient_id 由后端注入，不接受模型改写
            args = {k: v for k, v in raw_args.items() if k in props and k != "patient_id"}
            if "patient_id" in props:
                args["patient_id"] = patient_id
            return {"name": payload["name"], "arguments": args}
        except Exception as exc:
            logger.warning("LLM 工具选择失败，使用规则映射: %s", exc)
            return None

    async def answer(
        self,
        question: str,
        context: str = "",
        tool_result: str = "",
        history: str = "",
    ) -> str:
        if not self.available:
            return ""
        try:
            prompt = ANSWER_PROMPT.format(
                context=context or "（无）",
                tool_result=tool_result or "（无）",
                history=history[-1200:] or "无",
                question=question,
            )
            resp = await self._client().ainvoke(prompt)
            content = resp.content if isinstance(resp.content, str) else str(resp.content)
            return content.strip()
        except Exception as exc:
            logger.warning("LLM 生成失败，使用模板回答: %s", exc)
            return ""

    async def summarize(self, text: str, limit: int = 60) -> str:
        """工单标题摘要（可选）。"""
        if not self.available:
            return text[:limit]
        try:
            resp = await self._client().ainvoke(
                f"请把下面的患者问题概括为不超过 {limit} 个字的工单标题，只输出标题：\n{text}"
            )
            return (resp.content if isinstance(resp.content, str) else str(resp.content)).strip()[:limit]
        except Exception:
            return text[:limit]


llm_service = LLMService()

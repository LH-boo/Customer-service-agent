"""独立 MCP Server：以 stdio 方式暴露医院业务工具。

启动方式（通常由 Agent 作为 MCP Client 自动拉起）：
    python -m app.mcp.server

也可配合 MCP Inspector 调试：
    npx @modelcontextprotocol/inspector python -m app.mcp.server

安全说明：演示项目通过 patient_id 参数做数据隔离；生产环境应由 MCP Server 从
OAuth/内部令牌中解析患者身份，而不是信任调用方传入的参数。
"""
from __future__ import annotations

import asyncio
import logging
import sys
from typing import Optional

try:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP
except Exception:  # mcp 2.x: FastMCP 更名为 MCPServer
    from mcp.server.mcpserver import MCPServer as FastMCP

from app.database import engine, init_db
from app.services import business as svc

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s [mcp-server] %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

mcp = FastMCP("hospital-service")


@mcp.tool()
async def get_appointment(
    patient_id: int,
    appointment_no: Optional[str] = None,
    include_history: bool = False,
) -> dict:
    """查询患者本人的预约记录，返回科室、医生、就诊时间、状态与取消截止时间。"""
    return await svc.get_appointments(patient_id, appointment_no, include_history)


@mcp.tool()
async def cancel_appointment(patient_id: int, appointment_id: int) -> dict:
    """取消患者本人的预约。调用前必须已获得患者明确确认，并通过归属与时限校验。"""
    return await svc.cancel_appointment(patient_id, appointment_id)


@mcp.tool()
async def get_report_status(
    patient_id: int,
    report_no: Optional[str] = None,
    item_keyword: Optional[str] = None,
) -> dict:
    """查询患者本人检查报告的处理状态与更新时间，不提供报告结论。"""
    return await svc.get_report_status(patient_id, report_no, item_keyword)


@mcp.tool()
async def get_department_info(
    keyword: Optional[str] = None,
    department_name: Optional[str] = None,
) -> dict:
    """查询科室简介、位置和联系电话。"""
    return await svc.get_department_info(keyword, department_name)


@mcp.tool()
async def get_charge_detail(patient_id: int, visit_no: Optional[str] = None) -> dict:
    """查询患者本人本次就诊的费用明细与医保支付情况。"""
    return await svc.get_charge_detail(patient_id, visit_no)


@mcp.tool()
async def create_ticket(
    patient_id: int,
    title: str,
    content: str,
    category: str,
    priority: str = "normal",
    department: Optional[str] = None,
    need_human: bool = False,
) -> dict:
    """创建患者服务工单并分配处理部门。"""
    return await svc.create_ticket(
        patient_id=patient_id,
        title=title,
        content=content,
        category=category,
        priority=priority,
        department=department,
        need_human=need_human,
        operator="智能客服 Agent（MCP）",
    )


@mcp.tool()
async def get_ticket_status(patient_id: int, ticket_no: str) -> dict:
    """查询患者本人工单的处理状态与流转记录。"""
    return await svc.get_ticket_status(patient_id, ticket_no)


@mcp.tool()
async def assign_ticket(ticket_no: str, department: str, operator: str = "智能客服 Agent（MCP）") -> dict:
    """将工单分配给指定处理部门（内部工具）。"""
    return await svc.assign_ticket(ticket_no, department, operator)


@mcp.tool()
async def add_ticket_comment(
    ticket_no: str,
    content: str,
    operator: str = "系统",
    action: str = "comment",
) -> dict:
    """向工单追加一条处理记录（内部工具）。"""
    return await svc.add_ticket_comment(ticket_no, content, operator, action)


async def _prepare() -> None:
    await init_db(seed=False)
    await engine.dispose()


def main() -> None:
    asyncio.run(_prepare())
    logger.info("MCP Server 已启动（stdio）")
    mcp.run()


if __name__ == "__main__":
    main()

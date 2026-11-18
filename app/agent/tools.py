"""MCP 工具网关：对上层节点屏蔽「本地调用 / MCP Client」差异。"""
from __future__ import annotations

import logging
from typing import Any, Tuple

from app.config import settings
from app.mcp.client import mcp_client
from app.mcp.registry import get_handler

logger = logging.getLogger(__name__)


class ToolGateway:
    """所有业务工具调用的唯一入口。

    - MCP_MODE=local：直接调用业务服务（默认，启动快、便于本地演示）
    - MCP_MODE=client：通过 stdio 调用独立 MCP Server；失败自动降级并记录 transport
    """

    async def call(self, name: str, arguments: dict[str, Any]) -> Tuple[dict, str]:
        handler = get_handler(name)
        if handler is None:
            return {"ok": False, "error": f"未知工具: {name}"}, "none"

        if settings.mcp_mode == "client":
            try:
                result = await mcp_client.call(name, arguments)
                return result, "mcp"
            except Exception as exc:
                logger.warning("MCP 调用失败，降级为本地服务: %s", exc)

        try:
            result = await handler(**arguments)
            return result, "local"
        except Exception as exc:
            logger.exception("工具 %s 执行异常", name)
            return {"ok": False, "error": f"工具执行异常: {exc}"}, "local"


gateway = ToolGateway()

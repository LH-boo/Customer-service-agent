"""MCP Client：通过 stdio 连接独立 MCP Server 并调用工具。"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
from typing import Any, Dict

from app.config import BASE_DIR, settings

logger = logging.getLogger(__name__)


class MCPToolClient:
    def __init__(self) -> None:
        self.command = settings.mcp_server_command
        self.args = shlex.split(settings.mcp_server_args)
        self.timeout = settings.mcp_timeout_seconds

    async def call(self, name: str, arguments: Dict[str, Any]) -> dict:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        env = dict(os.environ)
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env.setdefault("PYTHONPATH", str(BASE_DIR))
        params = StdioServerParameters(command=self.command, args=self.args, env=env)

        async def _invoke() -> dict:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(name, arguments)
            if getattr(result, "isError", False):
                raise RuntimeError(f"MCP 工具返回错误: {name}")
            texts = [
                block.text
                for block in (result.content or [])
                if getattr(block, "type", None) == "text" and getattr(block, "text", None)
            ]
            if not texts:
                return {"ok": False, "error": "MCP 工具未返回文本结果"}
            return json.loads("".join(texts))

        return await asyncio.wait_for(_invoke(), timeout=self.timeout)


mcp_client = MCPToolClient()

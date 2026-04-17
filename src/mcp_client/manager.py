"""Manage multiple local MCP servers running over stdio.

- Loads server definitions from `config/mcp_servers.json`
- Spawns each as a subprocess
- Initializes an MCP session per server
- Aggregates their tools into an OpenAI-compatible tool list
- Routes tool calls to the right server
"""
from __future__ import annotations

import json
import os
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class MCPManager:
    def __init__(self, config_path: str) -> None:
        self.config_path = Path(config_path)
        self.exit_stack = AsyncExitStack()
        # server_name -> ClientSession
        self.sessions: dict[str, ClientSession] = {}
        # tool_name -> server_name (for routing)
        self._tool_routes: dict[str, str] = {}
        # OpenAI-format tool schemas
        self._tools_openai: list[dict[str, Any]] = []

    # ----- lifecycle ----------------------------------------------------

    async def __aenter__(self) -> "MCPManager":
        await self._connect_all()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.exit_stack.aclose()

    async def _connect_all(self) -> None:
        if not self.config_path.exists():
            raise FileNotFoundError(
                f"MCP config not found at {self.config_path}. "
                "Set MCP_CONFIG_PATH or create the file."
            )
        config = json.loads(self.config_path.read_text())
        servers = config.get("mcpServers", {})

        for name, spec in servers.items():
            if not spec.get("enabled", True):
                continue
            await self._connect_one(name, spec)

        await self._refresh_tools()

    async def _connect_one(self, name: str, spec: dict[str, Any]) -> None:
        env = os.environ.copy()
        env.update(spec.get("env", {}))

        params = StdioServerParameters(
            command=spec["command"],
            args=spec.get("args", []),
            env=env,
        )
        read, write = await self.exit_stack.enter_async_context(stdio_client(params))
        session = await self.exit_stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self.sessions[name] = session

    async def _refresh_tools(self) -> None:
        self._tool_routes.clear()
        self._tools_openai.clear()

        for server_name, session in self.sessions.items():
            result = await session.list_tools()
            for tool in result.tools:
                # Namespace tool name with server to avoid collisions
                qualified = f"{server_name}__{tool.name}"
                self._tool_routes[qualified] = server_name
                self._tools_openai.append(
                    {
                        "type": "function",
                        "function": {
                            "name": qualified,
                            "description": tool.description or "",
                            "parameters": tool.inputSchema
                            or {"type": "object", "properties": {}},
                        },
                    }
                )

    # ----- public API ---------------------------------------------------

    def openai_tools(self) -> list[dict[str, Any]]:
        return list(self._tools_openai)

    def list_tool_names(self) -> list[str]:
        return list(self._tool_routes.keys())

    async def call_tool(self, qualified_name: str, arguments: dict[str, Any]) -> str:
        """Call a tool by its qualified name; return a string result."""
        if qualified_name not in self._tool_routes:
            return f"ERROR: unknown tool '{qualified_name}'"

        server = self._tool_routes[qualified_name]
        # Strip the "<server>__" prefix to get the original tool name
        original = qualified_name[len(server) + 2 :]
        session = self.sessions[server]

        try:
            result = await session.call_tool(original, arguments)
        except Exception as e:  # noqa: BLE001
            return f"ERROR calling {qualified_name}: {e}"

        # Flatten content blocks to text
        parts: list[str] = []
        for block in result.content:
            text = getattr(block, "text", None)
            if text is not None:
                parts.append(text)
            else:
                parts.append(str(block))

        if getattr(result, "isError", False):
            return "TOOL_ERROR: " + "\n".join(parts)
        return "\n".join(parts) if parts else "(no output)"

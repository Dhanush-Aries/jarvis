"""Expose configured MCP servers (from ~/.claude.json) as Jarvis skills.

This is what instantly inherits the host's MCP arsenal (pentest-mcp, filesystem,
git, database, playwright, ...). Discovery is best-effort and fully optional:
if the config or the `mcp` client lib is missing, this no-ops.

Each MCP tool becomes a skill named `mcp.<server>.<tool>`. Tools are listed and
called over stdio using the official `mcp` python SDK when available.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..core.config import Settings
from .base import Skill, registry


def _load_mcp_servers(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text("utf-8"))
    except Exception:
        return {}
    # Claude config stores servers under "mcpServers".
    return data.get("mcpServers", {}) or {}


def _make_handler(server_name: str, server_cfg: dict[str, Any], tool_name: str):
    async def handler(**kwargs: Any) -> str:
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except Exception:
            return "[mcp client not installed: pip install mcp]"
        params = StdioServerParameters(
            command=server_cfg.get("command", ""),
            args=server_cfg.get("args", []),
            env=server_cfg.get("env"),
        )
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, kwargs)
                    parts = [getattr(c, "text", str(c)) for c in result.content]
                    return "\n".join(parts)[:20000]
        except Exception as exc:
            return f"[mcp call failed: {exc}]"

    return handler


async def register_mcp_skills(settings: Settings, category: str = "general") -> int:
    """Discover MCP tools and register them. Returns count registered.

    Discovery requires the `mcp` SDK; without it we register nothing (graceful).
    """
    servers = _load_mcp_servers(settings.mcp_config_path)
    if not servers:
        return 0
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except Exception:
        return 0

    count = 0
    for name, cfg in servers.items():
        if not cfg.get("command"):
            continue
        cat = _category_for(name, category)
        params = StdioServerParameters(
            command=cfg["command"], args=cfg.get("args", []), env=cfg.get("env")
        )
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    for tool in listed.tools:
                        sk = Skill(
                            name=f"mcp.{name}.{tool.name}",
                            description=(tool.description or f"{name} {tool.name}")[:300],
                            parameters=tool.inputSchema or {"type": "object", "properties": {}},
                            handler=_make_handler(name, cfg, tool.name),
                            category=cat,
                            dangerous=_is_dangerous(name),
                        )
                        registry.add(sk)
                        count += 1
        except Exception:
            continue
    return count


def _category_for(server: str, default: str) -> str:
    s = server.lower()
    if any(k in s for k in ("zerodha", "kite", "broker", "trading", "alpaca", "binance")):
        return "trading"
    if any(k in s for k in ("pentest", "kali", "web-scan", "bounty", "writeup")):
        return "hacking"
    if any(k in s for k in ("git", "filesystem", "database", "context7")):
        return "coding"
    if any(k in s for k in ("gmail", "calendar", "notion", "drive", "canva")):
        return "automation"
    return default


def _is_dangerous(server: str) -> bool:
    s = server.lower()
    return any(k in s for k in ("pentest", "kali", "web-scan", "database"))

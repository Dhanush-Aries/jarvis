"""Expose a full agentic Claude Code run as a Jarvis skill (Max/Pro powered).

`claude.code` hands a whole task to a Claude Code agent that uses its OWN tools,
MCP servers, and skills — driven by your subscription. This is how Jarvis can
actually *act* (edit files, run commands, drive MCP tools) on the Max plan, since
the subscription path doesn't expose native function-calling to the kernel loop.
"""
from __future__ import annotations

from ..providers import claude_code
from .base import Skill, registry


def register_claude_skills() -> int:
    if not claude_code.available():
        return 0

    async def handler(objective: str, cwd: str = "", autonomous: bool = True,
                      model: str = "sonnet") -> str:
        return await claude_code.adelegate(
            objective=objective, cwd=cwd or None, autonomous=autonomous, model=model
        )

    registry.add(Skill(
        name="claude.code",
        description="Delegate a complete task to an agentic Claude Code run powered "
        "by your Claude subscription. It can read/write files, run commands, and use "
        "MCP tools. Set autonomous=true to skip permission prompts (authorised work "
        "only). Use for multi-step coding, automation, or hacking sub-tasks.",
        parameters={
            "type": "object",
            "properties": {
                "objective": {"type": "string", "description": "The task to accomplish."},
                "cwd": {"type": "string", "description": "Working directory (optional)."},
                "autonomous": {"type": "boolean", "description": "Skip permission prompts."},
                "model": {"type": "string", "description": "sonnet | opus | haiku."},
            },
            "required": ["objective"],
        },
        handler=handler,
        category="coding",
        dangerous=True,
    ))
    return 1

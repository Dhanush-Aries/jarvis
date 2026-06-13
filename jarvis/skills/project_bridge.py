"""Bridge existing local agent projects (pentest-ai, decepticon) as skills.

These are heavyweight, optional capabilities. We expose them as a single
delegating skill each, invoked via their CLI, so Jarvis can hand off a whole
sub-task without importing their internals. Absent projects simply aren't
registered.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from .base import Skill, registry

_PROJECTS = {
    "pentest-ai": {
        "path": "~/pentest-ai",
        "name": "project.pentest_ai",
        "desc": "Delegate an autonomous web/API penetration test to the pentest-ai "
        "agent (200+ tools, exploit chaining). Input: target + objective.",
        "category": "hacking",
        "cmd": ["python", "-m", "pentest_ai"],
    },
    "decepticon": {
        "path": "~/decepticon",
        "name": "project.decepticon",
        "desc": "Delegate a multi-phase red-team campaign to the decepticon "
        "LangGraph framework. Input: scope + objective.",
        "category": "hacking",
        "cmd": ["python", "-m", "decepticon"],
    },
}


def _make_handler(project_path: Path, base_cmd: list[str]):
    async def handler(objective: str, target: str = "") -> str:
        cmd = base_cmd + ([target] if target else []) + ["--objective", objective]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(project_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=900)
        except asyncio.TimeoutError:
            proc.kill()
            return "[project run timed out after 900s]"
        return (out or b"").decode("utf-8", "replace")[:20000]

    return handler


def register_project_skills() -> int:
    count = 0
    for cfg in _PROJECTS.values():
        path = Path(os.path.expanduser(cfg["path"]))
        if not path.exists():
            continue
        registry.add(
            Skill(
                name=cfg["name"],
                description=cfg["desc"],
                parameters={
                    "type": "object",
                    "properties": {
                        "objective": {"type": "string", "description": "What to accomplish."},
                        "target": {"type": "string", "description": "Target host/scope."},
                    },
                    "required": ["objective"],
                },
                handler=_make_handler(path, cfg["cmd"]),
                category=cfg["category"],
                dangerous=True,
            )
        )
        count += 1
    return count

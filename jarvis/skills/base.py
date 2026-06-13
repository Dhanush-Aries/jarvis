"""Skill abstraction: a named, JSON-schema'd callable the agents can invoke.

Skills register three ways:
  1. @skill decorator (builtins / plugins),
  2. dynamically (MCP bridge, project bridge),
  3. drop-in python files in ~/.jarvis/plugins/.
"""
from __future__ import annotations

import importlib.util
import inspect
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from ..core.config import PLUGINS_DIR

Handler = Callable[..., Awaitable[Any]]


@dataclass
class Skill:
    name: str
    description: str
    parameters: dict[str, Any]          # JSON schema for arguments
    handler: Handler
    category: str = "general"           # general | coding | hacking | automation
    dangerous: bool = False             # gated by autonomy approval patterns

    def openai_tool(self) -> dict[str, Any]:
        """Render as an OpenAI/LiteLLM tool definition."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters or {"type": "object", "properties": {}},
            },
        }


class Registry:
    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def add(self, s: Skill) -> None:
        self._skills[s.name] = s

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def all(self) -> list[Skill]:
        return list(self._skills.values())

    def by_category(self, *categories: str) -> list[Skill]:
        # A skill is offered to an agent only if its category is one the agent
        # declares. "general" skills reach every agent because every agent lists
        # "general" among its categories — no special-casing needed.
        cats = set(categories)
        return [s for s in self._skills.values() if s.category in cats]

    def names(self) -> list[str]:
        return sorted(self._skills)


registry = Registry()


def skill(
    name: str | None = None,
    description: str = "",
    parameters: dict[str, Any] | None = None,
    category: str = "general",
    dangerous: bool = False,
) -> Callable[[Handler], Handler]:
    """Decorator registering an async function as a Skill."""

    def wrap(fn: Handler) -> Handler:
        sk = Skill(
            name=name or fn.__name__,
            description=description or (inspect.getdoc(fn) or "").strip(),
            parameters=parameters or {"type": "object", "properties": {}},
            handler=fn,
            category=category,
            dangerous=dangerous,
        )
        registry.add(sk)
        return fn

    return wrap


def load_plugins(directory: Path = PLUGINS_DIR) -> int:
    """Import every .py file in the plugins dir so its @skill calls register."""
    count = 0
    if not directory.exists():
        return 0
    for path in directory.glob("*.py"):
        spec = importlib.util.spec_from_file_location(f"jarvis_plugin_{path.stem}", path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(module)  # type: ignore[union-attr]
                count += 1
            except Exception:
                continue
    return count

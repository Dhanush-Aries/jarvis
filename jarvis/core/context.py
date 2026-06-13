"""Request/response dataclasses shared by every interface."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Source = Literal["cli", "web", "daemon", "voice", "api"]


@dataclass
class RequestContext:
    """A single user request, built by an interface and passed to the kernel."""

    text: str
    source: Source = "cli"
    session_id: str = "default"
    agent_hint: str | None = None          # force a specific agent if set
    autonomous: bool | None = None         # override config autonomy per-request
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Response:
    """The kernel's answer. `text` is the final reply; steps record tool calls."""

    text: str = ""
    agent: str = "chat"
    model: str = ""
    steps: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

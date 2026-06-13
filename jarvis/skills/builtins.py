"""Built-in skills available on every host: shell, file I/O, http."""
from __future__ import annotations

import asyncio
import shlex
from pathlib import Path

import httpx

from .base import skill

# Destructive shell patterns are tagged so the autonomy gate can intercept them.
_DESTRUCTIVE = ("rm ", "rm -", "mkfs", "dd ", ":(){", "shutdown", "reboot", "> /dev/")


@skill(
    name="shell.run",
    description="Run a shell command and return stdout/stderr. Use for system tasks, "
    "running tools, and chaining CLI utilities.",
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The shell command to run."},
            "timeout": {"type": "integer", "description": "Timeout seconds (default 120)."},
        },
        "required": ["command"],
    },
    category="general",
    dangerous=True,
)
async def shell_run(command: str, timeout: int = 120) -> str:
    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return f"[timeout after {timeout}s]"
    text = (out or b"").decode("utf-8", "replace")
    return text[:20000] if len(text) > 20000 else text


def is_destructive_command(command: str) -> bool:
    c = command.lower()
    return any(p in c for p in _DESTRUCTIVE)


@skill(
    name="file.read",
    description="Read a UTF-8 text file from disk.",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
)
async def file_read(path: str) -> str:
    p = Path(path).expanduser()
    if not p.exists():
        return f"[not found: {path}]"
    return p.read_text("utf-8", "replace")[:50000]


@skill(
    name="file.write",
    description="Write text to a file (creating parent dirs). Overwrites existing.",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
        "required": ["path", "content"],
    },
    category="coding",
    dangerous=True,
)
async def file_write(path: str, content: str) -> str:
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, "utf-8")
    return f"wrote {len(content)} bytes to {p}"


@skill(
    name="http.get",
    description="HTTP GET a URL and return status + body (truncated). For recon/lookup.",
    parameters={
        "type": "object",
        "properties": {"url": {"type": "string"}},
        "required": ["url"],
    },
)
async def http_get(url: str) -> str:
    async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
        r = await client.get(url)
        body = r.text[:8000]
        return f"HTTP {r.status_code}\n{body}"

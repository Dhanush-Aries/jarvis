"""Claude Code CLI provider — powers Jarvis from a Claude Max/Pro subscription.

The Max/Pro plan authenticates the `claude` CLI over OAuth, NOT the Anthropic API
(which LiteLLM uses and which is billed separately). So to use the subscription
we shell out to `claude -p` (print/non-interactive mode) and read the JSON result.

Two entry points:
  - `acomplete()`  : a plain text completion (used by the Router as a provider).
  - `adelegate()`  : hand a whole task to a full agentic Claude Code run that uses
                     ITS own tools/MCP servers/skills (used by the claude.code skill).
"""
from __future__ import annotations

import asyncio
import json
import shutil
from typing import Any

# Map Jarvis tier strings -> CLI model aliases.
_ALIASES = {
    "claude-sonnet-4-6": "sonnet",
    "claude-3-5-haiku-latest": "haiku",
    "claude-opus-4-8": "opus",
    "sonnet": "sonnet",
    "opus": "opus",
    "haiku": "haiku",
}


# Built-in Claude Code tools to disable on the COMPLETION path so it behaves as a
# pure text brain (and lets Jarvis's own agent loop drive skills uniformly across
# providers). The agentic `adelegate()` path deliberately keeps them enabled.
_NO_TOOLS = [
    "Bash", "Read", "Write", "Edit", "Glob", "Grep", "WebFetch", "WebSearch",
    "Task", "TodoWrite", "NotebookEdit", "BashOutput", "KillShell",
]


def available() -> bool:
    return shutil.which("claude") is not None


def model_alias(model: str) -> str:
    name = model.split("/", 1)[1] if "/" in model else model
    return _ALIASES.get(name, name)


def _flatten(messages: list[dict[str, Any]]) -> tuple[str, list[str]]:
    """Split into (prompt transcript, system prompts)."""
    systems: list[str] = []
    convo: list[str] = []
    for m in messages:
        role = m.get("role")
        content = m.get("content") or ""
        if role == "system":
            if content:
                systems.append(content)
        elif role == "tool":
            convo.append(f"[tool result]\n{content}")
        else:
            convo.append(f"{role}: {content}")
    return "\n\n".join(convo).strip(), systems


async def _run(cmd: list[str], stdin_text: str, timeout: int) -> dict[str, Any]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(
            proc.communicate(stdin_text.encode("utf-8")), timeout=timeout
        )
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError(f"claude CLI timed out after {timeout}s")
    if proc.returncode != 0 and not out:
        raise RuntimeError(f"claude CLI failed: {(err or b'').decode('utf-8', 'replace')[:400]}")
    try:
        return json.loads(out.decode("utf-8", "replace"))
    except Exception as exc:
        raise RuntimeError(f"claude CLI returned non-JSON: {exc}")


async def acomplete(messages: list[dict[str, Any]], model: str = "claude-code/sonnet",
                    timeout: int = 300, **_: Any) -> str:
    """Plain text completion via the subscription. Tools are not used here."""
    prompt, systems = _flatten(messages)
    # Plain completion = a pure text brain that obeys Jarvis's prompt/protocol:
    #   --strict-mcp-config + --setting-sources user : no MCP, no project CLAUDE.md
    #     (fast: ~4s vs minutes loading the whole harness)
    #   --disallowedTools + --exclude-dynamic-system-prompt-sections : disable Claude
    #     Code's own tools/persona so it doesn't act on its own and follows the
    #     text tool-protocol uniformly with every other provider
    #   --system-prompt : REPLACE the persona with Jarvis's system prompt
    system = "\n\n".join(systems) if systems else "You are a helpful assistant."
    cmd = [
        "claude", "-p", "--model", model_alias(model), "--output-format", "json",
        "--strict-mcp-config", "--setting-sources", "user",
        "--exclude-dynamic-system-prompt-sections",
        "--disallowedTools", *_NO_TOOLS,
        "--system-prompt", system,
    ]
    data = await _run(cmd, prompt, timeout)
    if data.get("is_error"):
        raise RuntimeError(data.get("result") or "claude CLI error")
    return data.get("result", "")


async def adelegate(objective: str, cwd: str | None = None, autonomous: bool = False,
                    model: str = "sonnet", timeout: int = 1800) -> str:
    """Run a full agentic Claude Code task (its own tools + your MCP servers).

    `autonomous=True` skips permission prompts so the run can edit files and run
    commands unattended — only do this for authorised, scoped work.
    """
    cmd = ["claude", "-p", "--model", model_alias(model), "--output-format", "json"]
    if autonomous:
        cmd += ["--permission-mode", "acceptEdits"]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(
            proc.communicate(objective.encode("utf-8")), timeout=timeout
        )
    except asyncio.TimeoutError:
        proc.kill()
        return f"[claude delegate timed out after {timeout}s]"
    try:
        data = json.loads(out.decode("utf-8", "replace"))
        return data.get("result", "") or (err or b"").decode("utf-8", "replace")[:2000]
    except Exception:
        return (out or b"").decode("utf-8", "replace")[:8000]

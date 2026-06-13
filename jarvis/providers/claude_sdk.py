"""Warm Claude Agent SDK sessions — fast Max-plan tool turns, no API key.

`claude -p` spawns a fresh ~5s process every call. The Agent SDK keeps ONE process
alive — and here we keep it alive ACROSS turns (a per-agent pool), so the ~3s
cold-start is paid once, not per request. Jarvis skills are exposed as REAL
in-process SDK tools, so Claude calls them natively (no text-protocol, no refusals)
and the session remembers context between turns. Same OAuth/Max auth as the CLI.
"""
from __future__ import annotations

import asyncio
import shutil

_ALIASES = {"claude-sonnet-4-6": "sonnet", "claude-3-5-haiku-latest": "haiku",
            "claude-opus-4-8": "opus"}


def available() -> bool:
    try:
        import claude_agent_sdk  # noqa: F401
    except Exception:
        return False
    return shutil.which("claude") is not None


def model_alias(model: str) -> str:
    name = model.split("/", 1)[1] if "/" in model else model
    return _ALIASES.get(name, name)


def _safe(name: str) -> str:
    return name.replace(".", "_").replace("-", "_")


class WarmSession:
    """A kept-alive Claude session with Jarvis skills bound as native tools.

    The autonomy gate is swapped in per-turn via `_gate`, so one warm session
    serves every request for its agent without rebuilding tools.
    """

    def __init__(self, model: str, system: str, skills: list) -> None:
        self.model = model
        self.system = system
        self.skills = skills
        self._client = None
        self._gate = lambda name, args: (True, "ok")
        self._lock = asyncio.Lock()

    def _build(self):
        from claude_agent_sdk import create_sdk_mcp_server, tool

        sdk_tools, allowed = [], []
        for sk in self.skills:
            allowed.append(f"mcp__jarvis__{_safe(sk.name)}")
            schema = sk.parameters if isinstance(sk.parameters, dict) else {}

            def make(skill):
                @tool(_safe(skill.name), (skill.description or skill.name)[:200], schema)
                async def handler(args):
                    ok, reason = self._gate(skill.name, args or {})
                    if not ok:
                        return {"content": [{"type": "text", "text": f"[blocked: {reason}]"}]}
                    try:
                        out = await skill.handler(**(args or {}))
                    except Exception as exc:
                        out = f"[error: {exc}]"
                    out = out if isinstance(out, str) else str(out)
                    return {"content": [{"type": "text", "text": out[:12000]}]}
                return handler

            sdk_tools.append(make(sk))
        return create_sdk_mcp_server("jarvis", "1.0.0", sdk_tools), allowed

    async def start(self) -> None:
        from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

        server, allowed = self._build()
        opts = ClaudeAgentOptions(
            model=self.model, system_prompt=self.system,
            mcp_servers={"jarvis": server}, allowed_tools=allowed, setting_sources=[],
        )
        self._client = ClaudeSDKClient(options=opts)
        await self._client.__aenter__()

    async def run(self, prompt: str, gate) -> tuple[str, list]:
        from claude_agent_sdk import AssistantMessage, TextBlock, ToolUseBlock

        async with self._lock:                      # one turn at a time per session
            if self._client is None:
                await self.start()
            self._gate = gate
            await self._client.query(prompt)
            text, steps = "", []
            async for msg in self._client.receive_response():
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            text += block.text
                        elif isinstance(block, ToolUseBlock) and \
                                block.name.startswith("mcp__jarvis__"):
                            steps.append(block.name.replace("mcp__jarvis__", ""))
            return text.strip(), steps

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.__aexit__(None, None, None)
            except Exception:
                pass
            self._client = None


# Per-agent warm-session pool (keyed by agent name + model).
_pool: dict[str, WarmSession] = {}


async def get_session(key: str, model: str, system: str, skills: list) -> WarmSession:
    sess = _pool.get(key)
    if sess is None:
        sess = WarmSession(model, system, skills)
        _pool[key] = sess
        await sess.start()
    return sess


async def prewarm(key: str, model: str, system: str, skills: list) -> None:
    """Spawn a session in the background so the first real request is fast."""
    try:
        await get_session(key, model, system, skills)
    except Exception:
        _pool.pop(key, None)


async def run_agentic(model: str, system: str, skills: list, gate, prompt: str,
                      key: str | None = None):
    """Run a turn via a warm pooled session (or a one-off if no key given)."""
    if key is not None:
        sess = await get_session(key, model, system, skills)
        try:
            return await sess.run(prompt, gate)
        except Exception:
            await sess.close()
            _pool.pop(key, None)            # drop a dead session, retry once fresh
            sess = await get_session(key, model, system, skills)
            return await sess.run(prompt, gate)
    sess = WarmSession(model, system, skills)
    try:
        return await sess.run(prompt, gate)
    finally:
        await sess.close()

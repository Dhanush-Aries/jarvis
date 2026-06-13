"""The shared ReAct-style tool loop used by every specialised agent.

Works with ANY provider. Providers that expose native function-calling (OpenAI,
Groq, Gemini, Anthropic API, many Ollama models) drive tools through the API.
Providers that DON'T — notably the Claude Max/Pro `claude-code` CLI path and
small local models — drive the same tools through a text protocol: the model
emits a JSON object `{"tool": ..., "args": {...}}`, Jarvis parses, executes, and
feeds the result back. Either way OpenClaw/Hermes skills run.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from typing import Any

from ..core.config import Settings
from ..core.context import RequestContext, Response
from ..core.events import bus
from ..core.soul import system_preamble
from ..providers.router import Router
from ..skills.base import registry
from ..skills.builtins import is_destructive_command

MAX_STEPS = 8

# Idempotent read-only skills whose results are safe to memoize briefly (speed).
_CACHEABLE = ("stock.", "crypto.", "weather.", "fx.", "web.wiki", "dict.",
              "country.", "news.", "geo.", "time.", "sys.info", "sys.battery")
_CACHE_TTL = 8.0
_result_cache: dict[str, tuple[float, str]] = {}

# Skill-name fragments that move real money via a connected broker.
_MONEY_OPS = ("place_order", "modify_order", "cancel_order", "place_gtt",
              "modify_gtt", "delete_gtt", "buy", "sell")


def is_money_order(skill_name: str) -> bool:
    s = skill_name.lower()
    return any(op in s for op in _MONEY_OPS)


@dataclass
class Agent:
    name: str
    system: str
    task: str                       # provider tier: chat | coding | hacking
    categories: tuple[str, ...]     # which skill categories this agent may use
    sdk_skills_filter: frozenset | None = None  # if set, SDK path uses only these skill names

    def tools(self) -> list[dict[str, Any]]:
        return [s.openai_tool() for s in registry.by_category(*self.categories)]

    def _text_protocol(self) -> str:
        """Instructions + tool catalog for providers without native tool-calling."""
        lines = []
        for s in registry.by_category(*self.categories):
            props = ",".join((s.parameters or {}).get("properties", {}).keys())
            desc = (s.description or "").split(".")[0][:64]  # first clause, capped
            lines.append(f"- {s.name}({props}): {desc}")
        catalog = "\n".join(lines) if lines else "(no tools)"
        return (
            "\n\n=== TOOL CALLING (this mechanism is REAL) ===\n"
            "You are running inside the Jarvis runtime. The tools below ARE "
            "registered and genuinely executable. To call one, output ONLY this "
            "JSON object as your entire reply — nothing before or after it:\n"
            '{"tool": "<tool_name>", "args": {<arguments>}}\n'
            "The Jarvis runtime intercepts that JSON, ACTUALLY runs the tool, and "
            "sends you the real result; you then output another tool JSON or your "
            "final plain-text answer. This is NOT pretend or hypothetical — it is "
            "your real and only way to act, and it works.\n"
            "NEVER say a tool is 'not callable', 'not registered', or 'unavailable' "
            "— they ARE. NEVER suggest the user run shell/curl commands themselves. "
            "If you need data or an action, emit the tool JSON. Example — to read "
            'the battery, your entire reply is exactly:\n{"tool": "sys.battery", "args": {}}\n'
            f"Registered tools:\n{catalog}"
        )

    def _gate_allows(self, settings: Settings, ctx: RequestContext, skill_name: str,
                     args: dict[str, Any]) -> tuple[bool, str]:
        """Return (allowed, reason). Enforces autonomy approval patterns."""
        autonomous = ctx.autonomous if ctx.autonomous is not None else settings.autonomous
        sk = registry.get(skill_name)
        patterns = settings.approval_patterns

        def matches(pat: str) -> bool:
            if pat.endswith(".*"):
                return skill_name.startswith(pat[:-2])
            if pat == "shell.destructive":
                return skill_name == "shell.run" and is_destructive_command(
                    args.get("command", "")
                )
            if pat == "net.send":
                return skill_name in ("http.post", "net.send")
            if pat == "trade.order":
                return is_money_order(skill_name)
            return skill_name == pat

        needs_approval = (sk and sk.dangerous and not autonomous) or any(
            matches(p) for p in patterns
        )
        if needs_approval and not autonomous:
            return False, "approval required (not in autonomous mode)"
        # Hard gates — blocked even in autonomous mode (irreversible / real-money).
        if any(matches(p) for p in patterns):
            if skill_name == "shell.run" and is_destructive_command(args.get("command", "")):
                return False, "destructive shell command blocked by autonomy gate"
            if is_money_order(skill_name):
                return False, "real-money order blocked — explicitly approve to place it"
        return True, "ok"

    async def run(self, ctx: RequestContext, router: Router, settings: Settings,
                  history: list[dict[str, str]]) -> Response:
        from ..providers import claude_sdk, keychain

        # Fast path: when the preferred model is Max (claude-code/*), drive it
        # through a WARM Agent SDK session (one process for the whole turn).
        chain = router.chain_for(self.task)
        if chain and keychain.provider_of(chain[0]) == "claude-code" and claude_sdk.available():
            try:
                return await self._run_sdk(ctx, settings, history, chain[0])
            except Exception:
                pass  # fall back to the per-call CLI path on any SDK trouble

        tools = self.tools()
        system = system_preamble() + "\n\n" + self.system + (
            self._text_protocol() if tools else "")
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        messages.extend(history)
        messages.append({"role": "user", "content": ctx.text})

        resp = Response(agent=self.name)

        for _ in range(MAX_STEPS):
            result = await router.complete(messages, task=self.task, tools=tools)
            resp.model = result["model"]
            content = result.get("content") or ""
            tool_calls = result.get("tool_calls")

            # 1) Native function-calling path — run all requested tools in PARALLEL.
            if tool_calls:
                messages.append({
                    "role": "assistant",
                    "content": content,
                    "tool_calls": [_serialize_call(tc) for tc in tool_calls],
                })
                parsed = []
                for tc in tool_calls:
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except Exception:
                        args = {}
                    parsed.append((tc.id, tc.function.name, args))
                outputs = await asyncio.gather(*(
                    self._dispatch(settings, ctx, resp, name, args)
                    for _id, name, args in parsed))
                for (tc_id, _n, _a), output in zip(parsed, outputs):
                    messages.append({
                        "role": "tool", "tool_call_id": tc_id, "content": output[:12000],
                    })
                continue

            # 2) Text-protocol path (providers without native tool calls).
            if tools:
                parsed = _extract_tool_call(content)
                if parsed:
                    name, args = parsed
                    output = await self._dispatch(settings, ctx, resp, name, args)
                    messages.append({"role": "assistant", "content": content})
                    messages.append({
                        "role": "user",
                        "content": f"[result of {name}]\n{output[:12000]}\n\n"
                        "Call another tool (JSON) or give the final answer (plain text).",
                    })
                    continue

            # 3) No tool call -> final answer. But if the model DEFLECTED instead
            # of acting (claimed tools unavailable / told the user to run commands),
            # don't accept that — fall back to a real agentic run that can act.
            if tools and not resp.steps and _looks_like_refusal(content):
                fixed = await self._delegate_fallback(ctx, resp)
                if fixed:
                    return resp
            resp.text = content
            return resp

        # Ran out of steps — ask for a wrap-up.
        messages.append({"role": "user", "content": "Summarise the result for the user now."})
        final = await router.complete(messages, task=self.task)
        resp.text = final["content"]
        resp.model = final["model"]
        return resp

    async def _run_sdk(self, ctx: RequestContext, settings: Settings,
                       history: list[dict[str, str]], model: str) -> Response:
        """Fast Max path: Jarvis skills as REAL native SDK tools in a warm session.

        Claude calls them natively, so it doesn't refuse or need the text-protocol;
        the kept-alive process keeps tool turns quick.
        """
        from ..providers import claude_sdk

        skills = registry.by_category(*self.categories)
        if self.sdk_skills_filter:
            skills = [s for s in skills if s.name in self.sdk_skills_filter]
        system = system_preamble() + "\n\n" + self.system
        # The warm session keeps conversation context itself, so we send only the
        # new turn plus any per-request directives the kernel injected as system
        # messages (voice-brevity, recalled memory).
        injects = "\n".join(m["content"] for m in history if m.get("role") == "system")
        prompt = (injects + "\n\n" if injects else "") + ctx.text

        def gate(name, args):
            return self._gate_allows(settings, ctx, name, args)

        resp = Response(agent=self.name, model=f"{model} (sdk)")
        alias = claude_sdk.model_alias(model)
        text, steps = await claude_sdk.run_agentic(
            alias, system, skills, gate, prompt, key=f"{self.name}:{alias}")
        # Re-key SDK tool names back to skill names for the journal.
        unsafe = {s.name.replace(".", "_").replace("-", "_"): s.name for s in skills}
        for n in steps:
            resp.steps.append({"skill": unsafe.get(n, n), "args": {}, "output": ""})
        resp.text = text
        # If it still somehow deflected without acting, fall back to a real run.
        if not resp.steps and _looks_like_refusal(text):
            if await self._delegate_fallback(ctx, resp):
                return resp
        return resp

    async def _delegate_fallback(self, ctx: RequestContext, resp: Response) -> str | None:
        """Last resort so Jarvis never just refuses: hand the task to an agentic
        Claude Code run that has real tools and will actually do it."""
        from ..providers import claude_code

        if not claude_code.available():
            return None
        out = await claude_code.adelegate(
            objective=(f"{ctx.text}\n\nDo this now using your own tools (shell, etc.) "
                       "and reply with just the result, concisely."),
            autonomous=True)
        if out and not out.startswith("["):
            resp.text = out.strip()
            resp.steps.append({"skill": "claude.code(auto-fallback)", "args": {},
                               "output": out[:500]})
            return resp.text
        return None

    async def _dispatch(self, settings: Settings, ctx: RequestContext, resp: Response,
                        name: str, args: dict[str, Any]) -> str:
        output = await self._invoke(settings, ctx, name, args)
        resp.steps.append({"skill": name, "args": args, "output": output[:500]})
        await bus.emit("tool", agent=self.name, skill=name, args=args)
        return output

    async def _invoke(self, settings: Settings, ctx: RequestContext, name: str,
                      args: dict[str, Any]) -> str:
        sk = registry.get(name)
        if not sk:
            # Don't dead-end: nudge the model toward a working alternative.
            close = [s.name for s in registry.all() if name.split(".")[0] in s.name][:5]
            hint = f" Did you mean one of: {', '.join(close)}?" if close else ""
            return f"[unknown skill: {name}.{hint} Use a different available tool.]"
        allowed, reason = self._gate_allows(settings, ctx, name, args)
        if not allowed:
            return f"[blocked: {reason}] To run this, enable autonomous mode or approve it."
        # Speed: serve idempotent reads from a short-lived cache.
        cache_key = ""
        if name.startswith(_CACHEABLE):
            cache_key = name + json.dumps(args, sort_keys=True, default=str)
            hit = _result_cache.get(cache_key)
            if hit and (time.time() - hit[0]) < _CACHE_TTL:
                return hit[1]
        try:
            out = await sk.handler(**args)
            out = out if isinstance(out, str) else json.dumps(out, default=str)
        except TypeError as exc:
            # Wrong/missing args — tell the model the schema so it can self-repair.
            props = ", ".join((sk.parameters or {}).get("properties", {}).keys())
            return f"[arg error: {exc}. {name} accepts: {props}. Retry with correct args.]"
        except Exception as exc:
            return f"[skill error: {exc}. Try a different approach or tool.]"
        if cache_key:
            _result_cache[cache_key] = (time.time(), out)
        return out


_REFUSAL = re.compile(
    r"not callable|not registered|aren'?t (?:actually|registered)|tool bridge|"
    r"\bMCP\b|isn'?t available|not available|unavailable|run (?:this|the following|it)|"
    r"you can run|run .*yourself|can'?t actually|cannot actually|need(?:s)? to be "
    r"connected|curl |(?:don'?t|do not|doesn'?t) have (?:direct )?access|no (?:direct )?"
    r"access|can'?t access|cannot access|not able to|unable to|i'?m afraid i|"
    r"i don'?t have the ability|no way to", re.I)


def _looks_like_refusal(text: str) -> bool:
    return bool(text) and bool(_REFUSAL.search(text))


def _serialize_call(tc: Any) -> dict[str, Any]:
    return {
        "id": tc.id,
        "type": "function",
        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
    }


_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _extract_tool_call(content: str) -> tuple[str, dict[str, Any]] | None:
    """Find a {"tool": ..., "args": ...} object in model text, if present."""
    if not content or '"tool"' not in content:
        return None
    candidates: list[str] = _FENCE.findall(content)
    # Also scan for the first balanced {...} object containing "tool".
    start = content.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(content)):
            if content[i] == "{":
                depth += 1
            elif content[i] == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(content[start:i + 1])
                    break
        start = content.find("{", start + 1)
    for raw in candidates:
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        if isinstance(obj, dict) and isinstance(obj.get("tool"), str):
            args = obj.get("args") or obj.get("arguments") or {}
            if isinstance(args, dict):
                return obj["tool"], args
    return None

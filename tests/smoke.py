"""Dependency-free smoke tests. Run: python tests/smoke.py

Covers the pure logic that must never regress: tool-call extraction, provider
usability/pruning, and the autonomy gate. No network, no models.
"""
from __future__ import annotations

import sys

from jarvis.agents.base_agent import Agent, _extract_tool_call
from jarvis.agents.registry import AGENTS, fast_route
from jarvis.core.capabilities import CapabilityReport
from jarvis.core.config import Settings
from jarvis.core.context import RequestContext
from jarvis.providers import keychain
from jarvis.skills.computer import register_computer_skills

register_computer_skills()  # so the gate test can resolve openclaw.* as dangerous

PASS, FAIL = 0, 0


def check(name: str, cond: bool) -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}")


print("tool-call extraction")
check("plain prose -> none", _extract_tool_call("just an answer, no tools") is None)
check("fenced json", _extract_tool_call('```json\n{"tool":"openclaw.screenshot","args":{}}\n```')
      == ("openclaw.screenshot", {}))
check("bare object", _extract_tool_call('sure: {"tool":"file.read","args":{"path":"/x"}}')
      == ("file.read", {"path": "/x"}))
check("arguments alias", _extract_tool_call('{"tool":"http.get","arguments":{"url":"u"}}')
      == ("http.get", {"url": "u"}))
check("object without tool key ignored",
      _extract_tool_call('{"foo":1, "bar":2}') is None)

print("keychain pruning")
caps = CapabilityReport(providers=["anthropic"], ollama=True,
                        ollama_models=["llama3.1:latest"], claude_code=True)
check("anthropic key usable", keychain.is_usable("claude-sonnet-4-6", caps))
check("openai pruned (no key)", not keychain.is_usable("gpt-4o", caps))
check("claude-code usable", keychain.is_usable("claude-code/sonnet", caps))
check("pulled ollama usable", keychain.is_usable("ollama/llama3.1", caps))
check("unpulled ollama pruned", not keychain.is_usable("ollama/qwen2.5-coder", caps))
chain = keychain.usable_chain(
    ["gpt-4o", "claude-code/sonnet", "ollama/qwen2.5-coder"], caps, "ollama/llama3.1")
check("chain prunes + appends fallback", chain == ["claude-code/sonnet", "ollama/llama3.1"])

print("autonomy gate")
ag: Agent = AGENTS["openclaw"]
auto = Settings(raw={"autonomy": {"mode": "autonomous",
                                  "approval_required_for": ["shell.destructive", "net.send"]}})
appr = Settings(raw={"autonomy": {"mode": "approval",
                                  "approval_required_for": ["shell.destructive"]}})
ctx = RequestContext(text="x")
ok, _ = ag._gate_allows(auto, ctx, "openclaw.screenshot", {})
check("autonomous allows dangerous skill", ok)
ok, _ = ag._gate_allows(appr, ctx, "openclaw.screenshot", {})
check("approval mode blocks dangerous skill", not ok)
ok, _ = ag._gate_allows(auto, ctx, "shell.run", {"command": "rm -rf /tmp/x"})
check("destructive shell hard-blocked even in auto", not ok)
ok, _ = ag._gate_allows(auto, ctx, "shell.run", {"command": "ls -la"})
check("safe shell allowed in auto", ok)
autot = Settings(raw={"autonomy": {"mode": "autonomous",
                                   "approval_required_for": ["trade.order"]}})
ok, _ = ag._gate_allows(autot, ctx, "mcp.Zerodha.place_order", {"symbol": "X"})
check("real-money order hard-blocked even in auto", not ok)
ok, _ = ag._gate_allows(autot, ctx, "stock.quote", {"symbol": "AAPL"})
check("read-only stock quote allowed", ok)

print("routing fast-path")
check("desktop -> openclaw", fast_route("open firefox and screenshot") == "openclaw")
check("hacking -> hacking", fast_route("scan for sqli and xss") == "hacking")
check("none for plain chat", fast_route("how are you today") is None)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)

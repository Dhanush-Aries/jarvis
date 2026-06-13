"""Detect which providers are usable and prune dead routes.

A model string is usable if either (a) its provider's API key is present, or
(b) it is an ollama/* model and Ollama is reachable. This is what lets Jarvis
answer with zero API keys.
"""
from __future__ import annotations

from ..core.capabilities import CapabilityReport

# Bare model names with no prefix are assumed Anthropic/OpenAI by their shape.
_ANTHROPIC_HINTS = ("claude",)
_OPENAI_HINTS = ("gpt-", "o1", "o3", "o4")


def provider_of(model: str) -> str:
    if "/" in model:
        return model.split("/", 1)[0]
    lower = model.lower()
    if any(h in lower for h in _ANTHROPIC_HINTS):
        return "anthropic"
    if any(lower.startswith(h) for h in _OPENAI_HINTS):
        return "openai"
    return "unknown"


def _ollama_pulled(model: str, caps: CapabilityReport) -> bool:
    """True if the ollama/<name> model is actually pulled (so calls don't fail).

    If we couldn't enumerate models (empty list), fall back to 'reachable' so we
    don't over-prune. Matches with or without an explicit ':tag'.
    """
    if not caps.ollama:
        return False
    if not caps.ollama_models:
        return True
    name = model.split("/", 1)[1] if "/" in model else model
    base = name.split(":", 1)[0]
    return any(m == name or m.split(":", 1)[0] == base for m in caps.ollama_models)


def is_usable(model: str, caps: CapabilityReport) -> bool:
    prov = provider_of(model)
    if prov == "ollama":
        return _ollama_pulled(model, caps)
    if prov == "claude-code":
        return caps.claude_code
    return prov in caps.providers


def usable_chain(models: list[str], caps: CapabilityReport, local_fallback: str) -> list[str]:
    """Filter to usable models, ensuring a local fallback is last when it's pulled."""
    chain = [m for m in models if is_usable(m, caps)]
    if is_usable(local_fallback, caps) and local_fallback not in chain:
        chain.append(local_fallback)
    return chain

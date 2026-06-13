"""LiteLLM-backed provider router with task-tier selection and fallback.

`complete()` tries each usable model in the tier chain in order, falling through
on error, and always ending at local Ollama if reachable.
"""
from __future__ import annotations

from typing import Any

from ..core.capabilities import CapabilityReport
from ..core.config import Settings
from . import keychain


class NoUsableModelError(RuntimeError):
    pass


class Router:
    def __init__(self, settings: Settings, caps: CapabilityReport) -> None:
        self.settings = settings
        self.caps = caps
        # Optional explicit aliases from config (model_list), name -> litellm_params.
        self._aliases = {
            m["model_name"]: m.get("litellm_params", {})
            for m in settings.model_list
            if "model_name" in m
        }

    def chain_for(self, task: str) -> list[str]:
        models = self.settings.tiers.get(task) or self.settings.tiers.get("chat", [])
        return keychain.usable_chain(models, self.caps, self.settings.fallback_local)

    def _params_for(self, model: str) -> dict[str, Any]:
        if model in self._aliases:
            return dict(self._aliases[model])
        params: dict[str, Any] = {"model": model}
        if keychain.provider_of(model) == "ollama":
            import os

            params["api_base"] = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
        return params

    async def complete(
        self,
        messages: list[dict[str, str]],
        task: str = "chat",
        tools: list[dict] | None = None,
        temperature: float = 0.3,
    ) -> dict[str, Any]:
        import litellm

        litellm.drop_params = True  # silently ignore params a provider doesn't support
        chain = self.chain_for(task)
        if not chain:
            raise NoUsableModelError(
                f"No usable model for task '{task}'. Set an API key or start Ollama "
                f"(ollama serve && ollama pull llama3.1)."
            )
        last_err: Exception | None = None
        for model in chain:
            # Claude Max/Pro subscription path: route through the `claude` CLI,
            # not the API. Native function-calling isn't exposed here, so tools
            # are ignored for this provider (use the claude.code skill to act).
            if keychain.provider_of(model) == "claude-code":
                from . import claude_code

                try:
                    text = await claude_code.acomplete(messages, model=model)
                    return {"model": model, "content": text, "tool_calls": None, "raw": text}
                except Exception as exc:
                    last_err = exc
                    continue

            params = self._params_for(model)
            try:
                kwargs: dict[str, Any] = dict(
                    messages=messages, temperature=temperature, **params
                )
                if tools:
                    kwargs["tools"] = tools
                    kwargs["tool_choice"] = "auto"
                resp = await litellm.acompletion(**kwargs)
                choice = resp.choices[0].message
                return {
                    "model": params.get("model", model),
                    "content": choice.get("content") or "",
                    "tool_calls": getattr(choice, "tool_calls", None),
                    "raw": choice,
                }
            except Exception as exc:  # fall through to next model in the chain
                last_err = exc
                continue
        raise NoUsableModelError(f"All models failed for task '{task}': {last_err}")

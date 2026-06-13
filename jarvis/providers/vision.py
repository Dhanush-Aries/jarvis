"""Vision backend — lets Jarvis SEE the screen, on any provider.

`see(image_path, instruction)` returns the model's text answer about the image.
Backend priority:
  1. Cloud vision via LiteLLM (OpenAI/Anthropic/Gemini) when a key is present.
  2. Claude CLI (Max/Pro) — reads the image with its Read tool.
  3. Local Ollama vision model (llava / llama3.2-vision) if pulled.
Returns a "[no vision backend]" string if none is available (caller degrades).
"""
from __future__ import annotations

import base64
import os
from pathlib import Path

from ..core.capabilities import CapabilityReport
from ..core.config import Settings

# Vision-capable cloud models, tried in order when their key exists.
_CLOUD_VISION = [
    ("openai", "gpt-4o"),
    ("anthropic", "claude-sonnet-4-6"),
    ("gemini", "gemini/gemini-1.5-pro"),
]
_OLLAMA_VISION = ("llava", "llama3.2-vision", "bakllava", "minicpm-v")


def _data_url(path: str) -> str:
    raw = Path(path).expanduser().read_bytes()
    return "data:image/png;base64," + base64.b64encode(raw).decode()


async def _via_litellm(model: str, image_path: str, instruction: str,
                       api_base: str | None = None) -> str:
    import litellm

    litellm.drop_params = True
    content = [
        {"type": "text", "text": instruction},
        {"type": "image_url", "image_url": {"url": _data_url(image_path)}},
    ]
    kwargs = {"model": model, "messages": [{"role": "user", "content": content}]}
    if api_base:
        kwargs["api_base"] = api_base
    resp = await litellm.acompletion(**kwargs)
    return resp.choices[0].message.get("content") or ""


async def _via_claude(image_path: str, instruction: str, model: str = "sonnet") -> str:
    import asyncio
    import json

    from . import claude_code

    prompt = (f"Read the image at {image_path}. {instruction}")
    cmd = ["claude", "-p", "--model", claude_code.model_alias(model),
           "--output-format", "json", "--allowedTools", "Read",
           "--strict-mcp-config", "--setting-sources", "user"]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(prompt.encode()), timeout=120)
        return json.loads(out.decode("utf-8", "replace")).get("result", "")
    except Exception as exc:
        return f"[claude vision failed: {exc}]"


async def see(image_path: str, instruction: str, caps: CapabilityReport,
              settings: Settings) -> str:
    if not Path(image_path).expanduser().exists():
        return f"[image not found: {image_path}]"

    for prov, model in _CLOUD_VISION:
        if prov in caps.providers:
            try:
                return await _via_litellm(model, image_path, instruction)
            except Exception:
                continue

    if caps.claude_code:
        return await _via_claude(image_path, instruction)

    vmodel = next((m for m in caps.ollama_models
                   if any(v in m for v in _OLLAMA_VISION)), None)
    if vmodel:
        host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
        try:
            return await _via_litellm(f"ollama/{vmodel}", image_path, instruction, api_base=host)
        except Exception as exc:
            return f"[ollama vision failed: {exc}]"

    return ("[no vision backend: set OPENAI/ANTHROPIC/GEMINI key, log into the "
            "claude CLI, or `ollama pull llava`]")

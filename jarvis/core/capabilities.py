"""Startup capability probing — the heart of 'works on any environment'.

Every optional feature consults the CapabilityReport and self-disables instead of
crashing when its dependency, key, or hardware is missing.
"""
from __future__ import annotations

import importlib.util
import os
import platform
import shutil
from dataclasses import dataclass, field
from typing import Any

from .config import Settings

_IS_MAC = platform.system() == "Darwin"

# Provider env-var -> the litellm provider prefix it unlocks.
PROVIDER_KEYS = {
    "ANTHROPIC_API_KEY": "anthropic",
    "OPENAI_API_KEY": "openai",
    "GROQ_API_KEY": "groq",
    "GEMINI_API_KEY": "gemini",
    "GOOGLE_API_KEY": "gemini",
    "MISTRAL_API_KEY": "mistral",
    "COHERE_API_KEY": "cohere",
    "TOGETHERAI_API_KEY": "together_ai",
    "DEEPSEEK_API_KEY": "deepseek",
    "OPENROUTER_API_KEY": "openrouter",
    "XAI_API_KEY": "xai",
}


def _module_present(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _ollama_probe() -> tuple[bool, list[str]]:
    """Return (reachable, pulled_model_names). Lets the router skip unpulled models."""
    host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
    try:
        import httpx

        r = httpx.get(host.rstrip("/") + "/api/tags", timeout=1.5)
        if r.status_code == 200:
            models = [m.get("name", "") for m in r.json().get("models", [])]
            return True, [m for m in models if m]
        return False, []
    except Exception:
        return shutil.which("ollama") is not None, []


def _audio_available() -> bool:
    if not _module_present("sounddevice"):
        return False
    try:
        import sounddevice as sd

        return any(d.get("max_input_channels", 0) > 0 for d in sd.query_devices())
    except Exception:
        return False


@dataclass
class CapabilityReport:
    os_name: str = ""
    python: str = ""
    providers: list[str] = field(default_factory=list)
    ollama: bool = False
    ollama_models: list[str] = field(default_factory=list)
    claude_code: bool = False
    voice_deps: bool = False
    audio_input: bool = False
    web_deps: bool = False
    daemon_deps: bool = False
    docker: bool = False
    desktop: dict[str, Any] = field(default_factory=dict)
    tools: dict[str, bool] = field(default_factory=dict)

    @property
    def has_any_provider(self) -> bool:
        return bool(self.providers) or self.ollama or self.claude_code

    @property
    def voice_ready(self) -> bool:
        return self.voice_deps and self.audio_input

    def as_dict(self) -> dict[str, Any]:
        return {
            "os": self.os_name,
            "python": self.python,
            "cloud_providers": self.providers,
            "claude_code (Max/Pro plan)": self.claude_code,
            "ollama": self.ollama,
            "voice_ready": self.voice_ready,
            "voice_deps": self.voice_deps,
            "audio_input": self.audio_input,
            "web_deps": self.web_deps,
            "daemon_deps": self.daemon_deps,
            "docker": self.docker,
            "desktop_control": self.desktop,
            "tools": self.tools,
        }


def _desktop_backends() -> dict[str, Any]:
    has = lambda *t: next((x for x in t if shutil.which(x)), None)  # noqa: E731
    return {
        "session": os.environ.get("XDG_SESSION_TYPE", "") or ("macos" if _IS_MAC else ""),
        "keyboard": has("wtype", "xdotool") or ("osascript" if _IS_MAC else None),
        "screenshot": has("grim", "scrot", "import") or ("screencapture" if _IS_MAC else None),
        "mouse_click": has("ydotool", "wlrctl", "xdotool"),
        "open_app": has("gtk-launch", "xdg-open", "open"),
        "browser": has("firefox", "google-chrome-stable", "chromium", "brave"),
    }


def probe(settings: Settings | None = None) -> CapabilityReport:
    providers = sorted({p for env, p in PROVIDER_KEYS.items() if os.environ.get(env)})
    claude_code = shutil.which("claude") is not None
    ollama_up, ollama_models = _ollama_probe()
    common_tools = ["git", "curl", "nmap", "ffmpeg", "docker", "ollama", "claude"]
    return CapabilityReport(
        desktop=_desktop_backends(),
        os_name=f"{platform.system()} {platform.release()}",
        python=platform.python_version(),
        providers=providers,
        ollama=ollama_up,
        ollama_models=ollama_models,
        claude_code=claude_code,
        voice_deps=_module_present("faster_whisper") and (
            _module_present("edge_tts") or _module_present("piper")
            or bool(shutil.which("espeak-ng") or shutil.which("say"))
        ),
        audio_input=_audio_available(),
        web_deps=_module_present("fastapi") and _module_present("uvicorn"),
        daemon_deps=_module_present("apscheduler"),
        docker=shutil.which("docker") is not None,
        tools={t: shutil.which(t) is not None for t in common_tools},
    )

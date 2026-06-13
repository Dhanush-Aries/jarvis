"""Configuration loading: config.yaml (non-secret) + .env (secrets).

Everything that is not a secret lives in config.yaml so the same file can be
committed and shared. Secrets (API keys) come only from the environment / .env.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# Resolve important paths once.
REPO_ROOT = Path(__file__).resolve().parents[2]
HOME_DIR = Path(os.environ.get("JARVIS_HOME", Path.home() / ".jarvis"))
DB_PATH = HOME_DIR / "jarvis.db"
PLUGINS_DIR = HOME_DIR / "plugins"


@dataclass
class Settings:
    """Typed view over config.yaml + environment."""

    raw: dict[str, Any] = field(default_factory=dict)

    # --- convenience accessors -------------------------------------------------
    @property
    def autonomy(self) -> dict[str, Any]:
        return self.raw.get("autonomy", {})

    @property
    def autonomous(self) -> bool:
        return bool(self.autonomy.get("mode", "autonomous") == "autonomous")

    @property
    def approval_patterns(self) -> list[str]:
        return list(self.autonomy.get("approval_required_for", []))

    @property
    def model_list(self) -> list[dict[str, Any]]:
        return self.raw.get("providers", {}).get("model_list", [])

    @property
    def tiers(self) -> dict[str, list[str]]:
        return self.raw.get("providers", {}).get("tiers", {})

    @property
    def fallback_local(self) -> str:
        return self.raw.get("providers", {}).get("local_fallback", "ollama/llama3.1")

    @property
    def voice(self) -> dict[str, Any]:
        return self.raw.get("voice", {})

    @property
    def web(self) -> dict[str, Any]:
        return self.raw.get("web", {"host": "127.0.0.1", "port": 8787})

    @property
    def mcp_config_path(self) -> Path:
        p = self.raw.get("skills", {}).get("mcp_config", "~/.claude.json")
        return Path(os.path.expanduser(p))

    def get(self, *keys: str, default: Any = None) -> Any:
        node: Any = self.raw
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return default
            node = node[k]
        return node


def load_settings(config_path: str | os.PathLike | None = None) -> Settings:
    """Load .env then config.yaml. Missing config.yaml -> built-in defaults."""
    load_dotenv(REPO_ROOT / ".env", override=False)
    load_dotenv(HOME_DIR / ".env", override=False)

    path = Path(config_path) if config_path else REPO_ROOT / "config.yaml"
    if path.exists():
        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    else:
        raw = _default_config()

    HOME_DIR.mkdir(parents=True, exist_ok=True)
    PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
    return Settings(raw=raw)


def _default_config() -> dict[str, Any]:
    """Sane defaults used when config.yaml is absent (portability guarantee)."""
    return {
        "providers": {
            "local_fallback": "ollama/llama3.1",
            "tiers": {
                "routing": ["groq/llama-3.1-8b-instant", "ollama/llama3.1"],
                "chat": ["claude-3-5-haiku-latest", "gpt-4o-mini", "ollama/llama3.1"],
                "coding": ["claude-sonnet-4-6", "gpt-4o", "ollama/qwen2.5-coder"],
                "hacking": ["claude-sonnet-4-6", "gpt-4o", "ollama/llama3.1"],
            },
            "model_list": [],
        },
        "autonomy": {
            "mode": "autonomous",
            "approval_required_for": ["shell.destructive", "hacking.*", "net.send"],
        },
        "skills": {"mcp_config": "~/.claude.json"},
        "voice": {"enabled": True, "wake_word": "jarvis", "tts_voice": "en_US-amy-medium"},
        "web": {"host": "127.0.0.1", "port": 8787},
    }

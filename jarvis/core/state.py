"""Tiny cross-process state channel for the visual UI.

The voice service writes its current state (idle/listening/thinking/speaking) to a
small JSON file; the arc-reactor page polls it. File-based so the (separate) voice
process and the reactor server stay fully decoupled — no sockets, no deps.
"""
from __future__ import annotations

import json
import time

from .config import HOME_DIR

STATE_FILE = HOME_DIR / "state.json"
VALID = ("idle", "listening", "thinking", "speaking")


def set_state(state: str, detail: str = "", transcript: str = "") -> None:
    try:
        HOME_DIR.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(
            json.dumps({"state": state, "detail": detail, "transcript": transcript, "t": time.time()}),
            encoding="utf-8",
        )
    except Exception:
        pass


def get_state() -> dict:
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        # Treat a stale state (>60s, e.g. service died) as idle.
        if time.time() - data.get("t", 0) > 60 and data.get("state") != "idle":
            data["state"] = "idle"
        return data
    except Exception:
        return {"state": "idle", "detail": "", "t": 0}

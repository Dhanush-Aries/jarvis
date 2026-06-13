"""Vosk STT backend — fast, real-time, fully offline (no GPU).

Much quicker than whisper for short voice commands, which is exactly the wake-word
+ command workload. Used as the primary STT when its model is present; the voice
loop falls back to faster-whisper otherwise.

Model dir: ~/.jarvis/vosk/<model>  (download the small English model once):
  curl -L -o m.zip https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
  unzip m.zip -d ~/.jarvis/vosk
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from ..core.config import HOME_DIR

VOSK_DIR = HOME_DIR / "vosk"


def _find_model() -> Path | None:
    if not VOSK_DIR.exists():
        return None
    for p in sorted(VOSK_DIR.iterdir()):
        if p.is_dir() and (p / "conf").exists():
            return p
    return None


class VoskSTT:
    """Drop-in transcribe(np_float32_16k) -> str, matching the whisper STT API."""

    def __init__(self, model_dir: Path) -> None:
        from vosk import Model, SetLogLevel

        SetLogLevel(-1)  # silence vosk's chatter
        self._model = Model(str(model_dir))

    def transcribe(self, audio) -> str:
        import numpy as np
        from vosk import KaldiRecognizer

        a = np.asarray(audio, dtype="float32").reshape(-1)
        pcm = (np.clip(a, -1.0, 1.0) * 32767).astype("<i2").tobytes()
        rec = KaldiRecognizer(self._model, 16000)
        rec.AcceptWaveform(pcm)
        try:
            return json.loads(rec.FinalResult()).get("text", "").strip()
        except Exception:
            return ""


def try_load() -> Optional["VoskSTT"]:
    model = _find_model()
    if model is None:
        return None
    try:
        return VoskSTT(model)
    except Exception:
        return None

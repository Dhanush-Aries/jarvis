"""Speech-to-text via faster-whisper. Optional; raises a clear error if absent."""
from __future__ import annotations

from typing import Optional


class STT:
    def __init__(self, model_size: str = "base.en") -> None:
        try:
            from faster_whisper import WhisperModel
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(
                "Voice STT needs faster-whisper: pip install 'jarvis-assistant[voice]'"
            ) from exc
        self._model = WhisperModel(model_size, device="auto", compute_type="int8")

    def transcribe(self, audio) -> str:
        segments, _ = self._model.transcribe(audio, language="en")
        return " ".join(s.text for s in segments).strip()


def try_load(model_size: str = "base.en") -> Optional["STT"]:
    try:
        return STT(model_size)
    except Exception:
        return None

"""Text-to-speech with layered backends, best first:

  1. edge-tts   — Microsoft neural voices (400+), online, no model download.
  2. piper      — fully offline neural TTS (needs a downloaded .onnx voice).
  3. espeak/say — system fallback.

`aspeak()` is async (edge-tts is async); `speak()` is a sync convenience wrapper.
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import tempfile

_URL = re.compile(r"https?://\S+")
_CODE = re.compile(r"```.*?```", re.DOTALL)
_EMOJI = re.compile("[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]")


def clean_for_speech(text: str) -> str:
    """Strip markdown/URLs/code/emoji so the voice reads naturally, not literally."""
    text = _CODE.sub(" (code omitted) ", text)
    text = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", text)  # [label](url) -> label (first!)
    text = _URL.sub(" link ", text)                  # then bare URLs
    text = _EMOJI.sub("", text)
    text = re.sub(r"[*_`#>|]+", "", text)            # markdown punctuation
    text = re.sub(r"^\s*[-•]\s*", "", text, flags=re.MULTILINE)  # bullets
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _player() -> str | None:
    for p in ("ffplay", "mpv", "afplay"):
        if shutil.which(p):
            return p
    if shutil.which("paplay") and shutil.which("ffmpeg"):
        return "paplay"
    return None


class TTS:
    def __init__(self, voice: str = "en-GB-RyanNeural", rate: str = "+8%",
                 pitch: str = "+0Hz") -> None:
        # Accept piper-style names too, but default to a natural Edge voice.
        self.voice = voice if "Neural" in voice or "-" in voice else "en-GB-RyanNeural"
        self.piper_voice = voice
        self.rate = rate
        self.pitch = pitch
        self._mode = self._detect()

    def _detect(self) -> str:
        try:
            import edge_tts  # noqa: F401
            if _player():
                return "edge"
        except Exception:
            pass
        try:
            import piper  # noqa: F401
            return "piper"
        except Exception:
            pass
        if shutil.which("say"):
            return "say"
        if shutil.which("espeak-ng") or shutil.which("espeak"):
            return "espeak"
        return "none"

    @property
    def available(self) -> bool:
        return self._mode != "none"

    @property
    def backend(self) -> str:
        return self._mode

    async def aspeak(self, text: str) -> None:
        text = clean_for_speech(text)
        if not text:
            return
        if self._mode == "edge":
            await self._edge(text)
        else:
            # piper/say/espeak are blocking; run off the event loop.
            await asyncio.to_thread(self._speak_sync, text)

    def speak(self, text: str) -> None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self.aspeak(text))
            return
        # Inside a running loop already — schedule synchronously via thread.
        self._speak_sync(text) if self._mode != "edge" else asyncio.run(self._edge(text))

    async def _edge(self, text: str) -> None:
        import edge_tts

        mp3 = os.path.join(tempfile.gettempdir(), "jarvis_tts.mp3")
        await edge_tts.Communicate(text, self.voice, rate=self.rate,
                                   pitch=self.pitch).save(mp3)
        self._play(mp3)

    def _play(self, path: str) -> None:
        player = _player()
        if player == "ffplay":
            subprocess.run(["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path],
                           check=False)
        elif player == "mpv":
            subprocess.run(["mpv", "--really-quiet", path], check=False)
        elif player == "afplay":
            subprocess.run(["afplay", path], check=False)
        elif player == "paplay":
            wav = path.rsplit(".", 1)[0] + ".wav"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "quiet", "-i", path, wav], check=False)
            subprocess.run(["paplay", wav], check=False)

    def _speak_sync(self, text: str) -> None:
        if self._mode == "piper":
            try:
                import numpy as np
                import sounddevice as sd
                from piper import PiperVoice

                voice = PiperVoice.load(self.piper_voice)
                pcm = b"".join(chunk.audio_int16_bytes for chunk in voice.synthesize(text))
                sd.play(np.frombuffer(pcm, dtype="int16"), voice.config.sample_rate)
                sd.wait()
            except Exception as exc:
                print(f"[piper failed: {exc}] {text}")
        elif self._mode == "say":
            subprocess.run(["say", text], check=False)
        elif self._mode == "espeak":
            exe = shutil.which("espeak-ng") or "espeak"
            subprocess.run([exe, text], check=False)
        else:
            print(f"[tts unavailable] {text}")

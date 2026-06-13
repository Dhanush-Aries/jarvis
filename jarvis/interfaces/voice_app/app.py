"""Always-listening voice loop — gap-free.

Earlier design recorded a fixed 2.5s then BLOCKED to transcribe, so the wake word
was missed if spoken during the transcription gap (and it burned CPU transcribing
silence). This version keeps ONE microphone stream open with a callback that never
drops audio, energy-gates so it only transcribes when you actually speak, and uses
the same stream for the request — so it hears you reliably and stays light.
"""
from __future__ import annotations

import asyncio
import queue
import random

# In-character voice cues (JARVIS from the films).
_ACK = ["Yes, sir?", "Sir?", "Standing by.", "Go ahead, sir.", "How can I help?"]
_WORKING = ["On it, sir.", "Right away.", "Let me see.", "One moment, sir.",
            "Pulling that up now.", "Working on it."]

from ...core.capabilities import probe
from ...core.config import load_settings
from ...core.context import RequestContext
from ...core.kernel import Kernel
from ...core.state import set_state

SR = 16000
BLOCK = int(0.1 * SR)          # 100 ms frames
VOICE_RMS = 0.012              # above this = speech
WAKE_WINDOW = 28               # frames (~2.8s) of rolling context for wake detect


async def run_voice() -> None:
    settings = load_settings()
    caps = probe(settings)
    if not caps.audio_input:
        print("No microphone / audio input detected. Voice interface unavailable.")
        print("Install: pip install -e '.[voice]'  and connect a mic.")
        return

    from ...voice.stt import try_load as whisper_load
    from ...voice.stt_vosk import try_load as vosk_load
    from ...voice.tts import TTS

    print("[voice] booting — loading the speech engine…", flush=True)
    # Vosk = fast real-time offline STT (preferred); faster-whisper = accurate fallback.
    stt = vosk_load()
    engine = "vosk (fast)"
    if stt is None:
        stt = whisper_load(settings.voice.get("stt_model", "base.en"))
        engine = "whisper"
    if stt is None:
        print("Voice STT dependencies missing. Run: pip install -e '.[voice]'  or  pip install vosk")
        return
    print(f"[voice] STT engine: {engine}", flush=True)
    v = settings.voice
    tts = TTS(v.get("tts_voice", "en-GB-RyanNeural"),
              rate=v.get("tts_rate", "+8%"), pitch=v.get("tts_pitch", "+0Hz"))

    import numpy as np
    import sounddevice as sd

    from ...voice.clap import count_claps

    wake = v.get("wake_word", "jarvis").lower()
    clap_on = bool(v.get("clap_to_wake", True))
    clap_n = int(v.get("clap_count", 2))

    # --- one continuous, never-dropping capture stream -----------------------
    q: queue.Queue = queue.Queue()

    def _cb(indata, frames, time_info, status):  # runs in PortAudio thread
        q.put(indata[:, 0].copy())

    stream = sd.InputStream(samplerate=SR, channels=1, dtype="float32",
                            blocksize=BLOCK, callback=_cb)
    stream.start()

    def rms(a) -> float:
        return float(np.sqrt(np.mean(a ** 2))) if len(a) else 0.0

    async def next_frame():
        # Pull the next 100ms frame without blocking the event loop.
        while True:
            try:
                return q.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.01)

    async def capture_utterance(max_s=10.0, silence_s=0.9, pre=None):
        """Collect frames until ~silence_s of quiet after speech (VAD)."""
        frames = list(pre) if pre else []
        quiet = 0.0
        spoke = False
        for _ in range(int(max_s / 0.1)):
            f = await next_frame()
            frames.append(f)
            if rms(f) > VOICE_RMS:
                spoke, quiet = True, 0.0
            elif spoke:
                quiet += 0.1
                if quiet >= silence_s:
                    break
        return np.concatenate(frames) if frames else np.zeros(1, "float32")

    # No MCP discovery — it spawns ~20 external servers and stalls startup. The
    # 62 built-in skills cover voice; run `jarvis chat` if you want MCP tools.
    kernel = await Kernel.create(with_mcp=False)

    # Pre-warm the chat session so the very first command is fast, not cold.
    from ...agents.registry import AGENTS
    from ...core.soul import system_preamble
    from ...providers import claude_sdk
    from ...skills.base import registry as _reg
    if claude_sdk.available():
        _a = AGENTS["chat"]
        _pw_skills = _reg.by_category(*_a.categories)
        if _a.sdk_skills_filter:
            _pw_skills = [s for s in _pw_skills if s.name in _a.sdk_skills_filter]
        asyncio.create_task(claude_sdk.prewarm(
            "chat:haiku", "haiku", system_preamble() + "\n\n" + _a.system, _pw_skills))

    trigger = f"say '{wake}'" + (f" or clap {clap_n}x" if clap_on else "")
    print(f"[voice] ✅ LISTENING now via {tts.backend} TTS — {trigger}, then speak. "
          f"(Ctrl-C to stop.)", flush=True)
    await tts.aspeak("Jarvis online.")
    set_state("idle")

    rolling: list = []
    try:
        while True:
            set_state("idle")
            f = await next_frame()
            rolling.append(f)
            if len(rolling) > WAKE_WINDOW:
                rolling.pop(0)

            inline = ""           # the request said in the same breath as the wake word
            # Clap trigger — cheap, no model.
            if clap_on and len(rolling) >= 6 and count_claps(
                    np.concatenate(rolling[-6:]), SR) >= clap_n:
                triggered = True
            elif rms(f) > VOICE_RMS and len(rolling) >= 10:
                # Speech detected — grab a longer window so a full "jarvis, do X"
                # command is captured in one go, then transcribe.
                window = await capture_utterance(max_s=6.0, silence_s=0.8,
                                                 pre=rolling[-10:])
                heard = stt.transcribe(window).lower().strip()
                triggered = wake in heard
                if triggered:
                    inline = heard[heard.rfind(wake) + len(wake):].strip(" ,.-?!")
            else:
                continue

            if not triggered:
                rolling.clear()
                continue
            rolling.clear()

            # If they said the command in one breath ("jarvis, what's the time"),
            # just do it — no "Yes?" interruption. Otherwise acknowledge and listen.
            if len(inline.split()) >= 2:
                request = inline
                set_state("thinking", request)
                await tts.aspeak(random.choice(_WORKING))
            else:
                set_state("listening")
                await tts.aspeak(random.choice(_ACK))
                audio = await capture_utterance(max_s=10.0, silence_s=0.9)
                request = stt.transcribe(audio).strip()
                if not request:
                    continue
                set_state("thinking", request)
                await tts.aspeak(random.choice(_WORKING))

            print(f"[you] {request}", flush=True)
            resp = await kernel.handle(RequestContext(
                text=request, source="voice", session_id="voice"))
            answer = resp.error or resp.text or "Done."
            print(f"[jarvis] {answer}", flush=True)
            set_state("speaking", answer[:120], transcript=request[:80])
            await tts.aspeak(answer)
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        set_state("idle")
        stream.stop()
        stream.close()
        await kernel.close()
        print("[voice] offline.")

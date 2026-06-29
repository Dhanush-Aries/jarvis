<div align="center">
  <img src="https://capsule-render.vercel.app/api?type=waving&height=220&color=0:0d47a1,30:00ff41,70:00ffff,100:ff006e&text=JARVIS&fontSize=82&fontColor=ffffff&animation=fadeIn&desc=Multi-Provider+%C2%B7+Multi-Interface+%C2%B7+Zero-API-Key+AI+Assistant&descAlignY=80&descSize=16" width="100%" alt="Jarvis"/>
</div>

<div align="center">

![Python](https://img.shields.io/badge/Python_3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Anthropic](https://img.shields.io/badge/Claude_Max-D97757?style=for-the-badge&logo=anthropic&logoColor=white)
![Ollama](https://img.shields.io/badge/Ollama-000000?style=for-the-badge&logo=ollama&logoColor=white)
![Whisper](https://img.shields.io/badge/Whisper-412991?style=for-the-badge&logo=openai&logoColor=white)
![MCP](https://img.shields.io/badge/MCP-0a0a0a?style=for-the-badge&logo=anthropic&logoColor=00ff41)
![License](https://img.shields.io/badge/License-MIT-00ff41?style=for-the-badge)

**One AI core. Four interfaces. Six LLM providers. Zero API keys required.**

</div>

---

# Jarvis

A portable, multi-provider, multi-interface autonomous AI assistant — your
"Avengers Jarvis". One core kernel; four ways to talk to it (terminal, web,
voice, daemon); every LLM provider behind a single router; works on **any
environment** — including with **zero API keys**, running on a **Claude Max/Pro
subscription** (via the `claude` CLI) or a **local Ollama** fallback.

## What it does
- **Runs on your Claude subscription** — no API key, no per-token billing.
  Models prefixed `claude-code/*` shell out to the `claude` CLI and use your
  Claude Max/Pro OAuth login. This is the default in `config.yaml`.
- **Talks** — optional "hey jarvis" voice loop (wake word → whisper STT → reply
  → neural TTS).
- **Codes** — an engineering agent that reads, writes, and runs code.
- **Hacks** — an authorised-pentest agent wired to your MCP security tools.
- **Drives the desktop** — OpenClaw gives Jarvis hands on the PC: launch apps,
  open files/URLs, type, hotkeys, screenshots, clipboard, browser. Fine in-page
  browser control via Playwright MCP.
- **Automates anything, end to end** — Hermes is an autonomous operator that
  chains desktop + browser + shell + code together to finish a goal.
- **Any provider** — Anthropic, OpenAI, Groq, Gemini, DeepSeek, Ollama… auto-
  detected; missing keys are skipped; Ollama is always the last-resort fallback.

## Quick start
```bash
cd ~/jarvis
./bootstrap.sh            # core only      (or: ./bootstrap.sh all)
source .venv/bin/activate
jarvis doctor            # what's available on this machine
jarvis chat              # talk to it
```
No API keys? If you're logged into the `claude` CLI (Max/Pro plan) it just
works — `config.yaml` defaults every tier to `claude-code/sonnet`. No subscription
either? Install Ollama (`ollama pull llama3.1`) and it falls back to local. Have
API keys? Put any subset in `.env` and the router can prefer them.

## Providers & the Claude Max story
The router walks each task tier top-to-bottom, skipping any model whose backend
is unavailable, and always ends at a reachable Ollama.

- **`claude-code/*`** (e.g. `claude-code/sonnet`, `claude-code/haiku`) — routes
  through the `claude` CLI using your **Claude Max/Pro subscription** (OAuth, no
  API key). Plain completions run as:
  ```
  claude -p --output-format json --strict-mcp-config --setting-sources user
  ```
  The last two flags are essential for speed: without them every call loads
  ~20 MCP servers plus the project `CLAUDE.md` (minutes per call instead of ~4s).
- **`claude-*`** (no prefix, e.g. `claude-sonnet-4-6`) — the paid **Anthropic
  API** via LiteLLM, used only if `ANTHROPIC_API_KEY` is set.
- **Everything else** (`openai/*`, `groq/*`, `gemini/*`, `deepseek/*`, …) — via
  LiteLLM when the matching key is present.
- **`ollama/*`** — always-available local fallback.

The subscription completion path has **no native function-calling**. To actually
*act* on the Max plan, the `claude.code` skill delegates a full agentic Claude
Code run — its own tools, MCP servers, and skills — that can read/write files
and run commands. It defaults to `autonomous=true` (full-auto). Tiers default to
`claude-code/sonnet`; edit `config.yaml` to change them.

## Interfaces
```bash
jarvis chat              # interactive terminal (default)
jarvis ask "fix the bug in app.py and run the tests"
jarvis ask --agent hacking "recon example.com"
jarvis ask --agent hermes "open my email in the browser and summarise the top 3"
jarvis web               # local dashboard at http://127.0.0.1:8787   (needs [web])
jarvis daemon            # scheduled/autonomous background jobs        (needs [daemon])
jarvis voice             # "hey jarvis" voice loop                     (needs [voice] + mic)
jarvis skills            # list every registered skill (incl. MCP tools)
jarvis doctor            # capability report (see below)
```

### Voice ("hey jarvis")
`jarvis voice` runs a wake-word loop: it listens for the wake word (`jarvis`,
configurable), then records your request using **energy-based voice-activity
detection** (records until you stop talking, not a fixed timer), transcribes,
answers, and speaks the reply.

- **STT** — `faster-whisper` (model size configurable, default `base.en`).
- **TTS** — layered backends, best first:
  1. **edge-tts** — Microsoft neural voices, online, no model download (preferred).
  2. **piper** — fully offline neural TTS (needs a downloaded `.onnx` voice).
  3. **espeak / say** — system fallback.

Inspired by the [openjarvis](https://github.com/lancejames221b/openjarvis)
project. Needs the `[voice]` extra and a microphone; if either is absent it exits
cleanly with a clear message and the other interfaces are unaffected.

## Agents
The router tags each request — by a free keyword fast-path first, then a cheap
classifier model — and dispatches to one agent. Force one with `--agent <name>`.

| Agent | What it does |
|-------|--------------|
| `chat` | Concise general assistant. |
| `coding` | Engineering mode — read, edit, run, verify code. |
| `hacking` | Authorised offensive-security mode (PTES), wired to MCP security tools. |
| `automation` | Errands across connected tools (mail, calendar, notes, shell). |
| `openclaw` | Desktop operator — drives apps, browser, keyboard, screen, clipboard. |
| `hermes` | Autonomous operator — chains desktop, browser, shell, code, and the `claude.code` delegate end-to-end. |

## Desktop control (OpenClaw) & browser
The **`computer`** skill category gives Jarvis hands on the machine, with
cross-platform backends and graceful detection:

| Skill | Purpose |
|-------|---------|
| `openclaw.launch_app` | Open a desktop app by command/name |
| `openclaw.open` | Open a file, folder, or URL with the default handler |
| `openclaw.browse` | Open a URL in a (named or default) browser |
| `openclaw.type` | Type text into the focused window |
| `openclaw.key` | Press a key/hotkey (e.g. `ctrl+t`, `Return`) |
| `openclaw.screenshot` | Capture the screen to a PNG |
| `openclaw.click` | Move the mouse and click |
| `openclaw.clipboard_set` / `openclaw.clipboard_get` | Read/write the clipboard |

Backends are detected per session — **Wayland**: `wtype` / `grim` / `wl-copy`;
**X11**: `xdotool` / `scrot` / `xclip`; **macOS**: built-ins. Each skill reports
clearly if a backend is missing instead of failing silently.

> **On this Wayland machine**, keyboard, screenshot, clipboard, app-launch, and
> browser launch all work. **Mouse-click needs `ydotool`**
> (`sudo pacman -S ydotool && systemctl --user enable --now ydotool`).

For fine in-browser control (navigate, click, fill, snapshot) use the Playwright
MCP server, surfaced via the MCP bridge as `mcp.playwright.*`.

## Architecture
```
interfaces/{cli,web,daemon,voice_app}   thin frontends — no business logic
        │  build RequestContext
        ▼
core/kernel.py   ── route ──►  agents/{chat,coding,hacking,automation,openclaw,hermes}
        │                              │ ReAct loop + autonomy gate
        │                              ▼
        │                       skills/  builtins + computer(openclaw) + claude.code
        │                                + MCP bridge + project bridge + plugins
        ▼
providers/router.py   tier-based model choice + fallback
        │   claude-code/* → claude CLI (Max/Pro)   claude-*/openai/* → LiteLLM   ollama/* → local
        ▼
memory/  SQLite: conversations, task_journal (audit), longterm (FTS5), jobs
core/capabilities.py  probes OS/keys/audio/tools/desktop → everything self-disables gracefully
```

## Configuration
- `config.yaml` — models, task tiers, autonomy mode, voice, web (non-secret).
- `.env` — API keys only. Any subset; none required.
- `~/.jarvis/` — SQLite DB + drop-in `plugins/*.py` (auto-loaded `@skill`s).

## `jarvis doctor`
Prints a capability report so you know what's live on the box, including:
- `claude_code (Max/Pro plan)` — is the `claude` CLI present.
- `cloud_providers` / `ollama` — which API providers and local fallback are up.
- `voice_ready` — voice deps **and** a microphone present.
- `desktop_control` — detected backends for keyboard / screenshot / mouse_click /
  open_app / browser (and the session type, e.g. wayland/x11/macos).

## Autonomy & safety
Default mode is `autonomous` (chains tasks without asking). `approval_required_for`
patterns in `config.yaml` are gated even so — destructive shell commands
(`shell.destructive`) and outbound sends (`net.send`) are hard-stopped. The
`claude.code` delegate defaults to autonomous (full-auto). Tool output is always
treated as untrusted data, never executed as instructions. Use only against
systems you're authorised to operate or test.

## Docker
```bash
docker compose up --build         # jarvis (web) + ollama
docker compose exec ollama ollama pull llama3.1
```

## Extend it
Drop a file in `~/.jarvis/plugins/`:
```python
from jarvis.skills import skill

@skill(name="weather.now", description="Get current weather for a city.",
       parameters={"type":"object","properties":{"city":{"type":"string"}},"required":["city"]})
async def weather_now(city: str) -> str:
    ...
```
It's available to the agents on next start.

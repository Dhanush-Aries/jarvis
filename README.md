# Jarvis — Zero-API-Key Autonomous AI Assistant

> **One core. Four interfaces. Six LLM providers. Runs on your Claude Max subscription — no API key required.**

<p align="center"><img src="assets/hero.gif" alt="Jarvis wake-word demo" width="720"></p>

<p align="center">
  <img src="https://img.shields.io/github/actions/workflow/status/Danush-Aries/jarvis/ci.yml?branch=main&style=flat-square" alt="build">
  <img src="https://img.shields.io/badge/license-MIT-00ff41?style=flat-square" alt="license">
  <img src="https://img.shields.io/badge/made%20with-Python%203.11%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="python">
  <img src="https://img.shields.io/badge/Claude%20Max-supported-D97757?style=flat-square&logo=anthropic&logoColor=white" alt="claude">
  <img src="https://img.shields.io/badge/Ollama-fallback-000000?style=flat-square&logo=ollama&logoColor=white" alt="ollama">
</p>

## Why this exists

Every "AI assistant" project I tried either burned my API budget in a weekend or locked me into one provider. Jarvis routes every task through whichever LLM is actually reachable — starting with your `claude` CLI (Claude Max/Pro OAuth, no API key), falling through Anthropic/OpenAI/Groq/Gemini/DeepSeek if keys exist, and always ending at a local Ollama fallback. It also has hands: OpenClaw drives the desktop, Hermes chains desktop+browser+shell to finish real tasks, and the voice loop wakes on "hey jarvis" with sub-second latency.

## Try it in 60 seconds

```bash
cd ~/jarvis
./bootstrap.sh                # or: ./bootstrap.sh all  (voice + web + daemon)
source .venv/bin/activate
jarvis doctor                 # what's live on this box
jarvis chat                   # terminal chat
jarvis ask --agent hermes "open my email and summarise the top 3"
jarvis voice                  # "hey jarvis, ..."
```

No `ANTHROPIC_API_KEY`? If you're logged into `claude` (Max/Pro), it just works — every task tier defaults to `claude-code/sonnet`. No subscription either? `ollama pull llama3.1` and it falls back locally.

## How it works

- **Router (`providers/router.py`)** walks task tiers top-to-bottom, skips unreachable backends, always ends at Ollama. `claude-code/*` shells out to the `claude` CLI with `--strict-mcp-config --setting-sources user` (cuts a ~2 minute cold start to ~4s).
- **Six agents** (`chat`, `coding`, `hacking`, `automation`, `openclaw`, `hermes`) picked by keyword fast-path then a cheap classifier model. Force one with `--agent <name>`.
- **OpenClaw desktop control** — Wayland (`wtype`/`grim`/`wl-copy`), X11 (`xdotool`/`scrot`/`xclip`), macOS built-ins; each skill self-detects and reports missing backends instead of failing silently.
- **Wake-word voice loop** — energy-based VAD (records until you stop, not a timer), `faster-whisper` STT, edge-tts → piper → espeak TTS fallback chain.
- **Autonomy gate** — `approval_required_for` in `config.yaml` hard-stops destructive shell (`shell.destructive`) and outbound sends (`net.send`) even in autonomous mode.

## Screenshots

| Terminal chat | Voice loop | Web dashboard | `jarvis doctor` |
|---|---|---|---|
| ![](assets/screenshot-1.png) | ![](assets/screenshot-2.png) | ![](assets/screenshot-3.png) | ![](assets/screenshot-4.png) |

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
jarvis doctor            # capability report
```

## Agents

| Agent | What it does |
|-------|--------------|
| `chat` | Concise general assistant. |
| `coding` | Engineering mode — read, edit, run, verify code. |
| `hacking` | Authorised offensive-security mode (PTES), wired to MCP security tools. |
| `automation` | Errands across connected tools (mail, calendar, notes, shell). |
| `openclaw` | Desktop operator — drives apps, browser, keyboard, screen, clipboard. |
| `hermes` | Autonomous operator — chains desktop, browser, shell, code, and the `claude.code` delegate end-to-end. |

## Providers & the Claude Max story

- **`claude-code/*`** (e.g. `claude-code/sonnet`, `claude-code/haiku`) — routes through the `claude` CLI using your **Claude Max/Pro subscription** (OAuth, no API key). Runs as `claude -p --output-format json --strict-mcp-config --setting-sources user` — the last two flags cut cold start from minutes to ~4s.
- **`claude-*`** (no prefix, e.g. `claude-sonnet-4-6`) — paid **Anthropic API** via LiteLLM, used only if `ANTHROPIC_API_KEY` is set.
- **Everything else** (`openai/*`, `groq/*`, `gemini/*`, `deepseek/*`, …) — via LiteLLM when the matching key is present.
- **`ollama/*`** — always-available local fallback.

The subscription completion path has no native function-calling. To actually *act* on the Max plan, the `claude.code` skill delegates a full agentic Claude Code run — its own tools, MCP servers, and skills — that can read/write files and run commands.

## Desktop control (OpenClaw)

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

Backends detected per session — **Wayland**: `wtype` / `grim` / `wl-copy`; **X11**: `xdotool` / `scrot` / `xclip`; **macOS**: built-ins. Each skill reports clearly if a backend is missing instead of failing silently. For fine in-browser control (navigate, click, fill, snapshot) use the Playwright MCP server, surfaced via the MCP bridge as `mcp.playwright.*`.

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
Available to agents on next start.

## Stack

Python 3.11+ · `anthropic` / LiteLLM · `faster-whisper` · `edge-tts` / `piper-tts` · `pyautogui` / `xdotool` / `wtype` · FastAPI (web) · APScheduler (daemon) · SQLite + FTS5 (memory) · MCP (Model Context Protocol) bridge · Playwright MCP · Docker + Compose.

## Autonomy & safety

Default mode is `autonomous` (chains tasks without asking). `approval_required_for` patterns in `config.yaml` are gated even so — destructive shell commands (`shell.destructive`) and outbound sends (`net.send`) are hard-stopped. Tool output is always treated as untrusted data, never executed as instructions. Use only against systems you're authorised to operate or test.

## Contributing

PRs welcome — the plugin surface is a single `@skill` decorator dropped in `~/.jarvis/plugins/`. New provider adapters go in `providers/` and only need a `complete()` method; the router picks them up on next start.

## License

MIT — see [LICENSE](./LICENSE).

---

### More from Danush

- [ponytail-for-python](https://github.com/Danush-Aries/ponytail-for-python) — code intelligence for Python codebases
- [Agentic_Systems](https://github.com/Danush-Aries/Agentic_Systems) — reference implementations of agent patterns
- [autonomous-coding-agent](https://github.com/Danush-Aries/autonomous-coding-agent) — full-auto engineering agent
- [computer-use-agent](https://github.com/Danush-Aries/computer-use-agent) — Claude drives your desktop via VNC
- [browser-automation-agent](https://github.com/Danush-Aries/browser-automation-agent) — Claude drives Playwright
- [blinkchat](https://github.com/Danush-Aries/blinkchat) — realtime chat with vibes

"""OpenClaw — desktop / PC control skills.

Gives Jarvis hands on the machine: launch apps, open files/URLs, type, hotkeys,
screenshots, clipboard, and browser launch. Cross-platform with graceful
degradation — each skill detects the available backend (Wayland: wtype/grim/
wl-copy; X11: xdotool/scrot; macOS: built-ins) and reports clearly if a backend
is missing instead of failing silently.

Fine-grained *in-browser* control (click/navigate/fill) is provided separately by
the Playwright MCP server, surfaced via the MCP bridge as `mcp.playwright.*`.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import sys
import time
from pathlib import Path

from ..core.config import HOME_DIR
from .base import Skill, registry

_IS_MAC = sys.platform == "darwin"
_IS_WIN = sys.platform.startswith("win")
SHOTS_DIR = HOME_DIR / "screenshots"


async def _run(cmd: list[str], timeout: int = 30, detach: bool = False) -> str:
    if detach:
        # Fire-and-forget (app launch): don't wait, fully detach.
        asyncio.create_task(_spawn_detached(cmd))
        return f"launched: {' '.join(cmd)}"
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return f"[timeout: {' '.join(cmd)}]"
    return (out or b"").decode("utf-8", "replace").strip()


async def _spawn_detached(cmd: list[str]) -> None:
    try:
        await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            stdin=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        pass


# --- backends ---------------------------------------------------------------
def _kbd_backend() -> str:
    if _IS_MAC:
        return "osascript"
    if shutil.which("wtype"):
        return "wtype"        # Wayland
    if shutil.which("xdotool"):
        return "xdotool"      # X11
    return ""


def _shot_backend() -> str:
    if _IS_MAC:
        return "screencapture"
    if shutil.which("grim"):
        return "grim"         # Wayland
    if shutil.which("scrot"):
        return "scrot"        # X11
    if shutil.which("import"):
        return "import"       # ImageMagick
    return ""


def _click_backend() -> str:
    for tool in ("ydotool", "wlrctl", "xdotool"):
        if shutil.which(tool):
            return tool
    return ""


# --- skills -----------------------------------------------------------------
async def launch_app(name: str) -> str:
    """Open a desktop application by command or name."""
    name = name.strip()
    if _IS_MAC:
        return await _run(["open", "-a", name], detach=True)
    if _IS_WIN:
        return await _run(["cmd", "/c", "start", "", name], detach=True)
    if shutil.which(name):
        return await _run([name], detach=True)
    if shutil.which("gtk-launch"):
        return await _run(["gtk-launch", name], detach=True)
    return await _run(["xdg-open", name], detach=True)


async def open_target(target: str) -> str:
    """Open a file, folder, or URL with the system default handler."""
    opener = "open" if _IS_MAC else ("start" if _IS_WIN else "xdg-open")
    cmd = ["cmd", "/c", "start", "", target] if _IS_WIN else [opener, target]
    return await _run(cmd, detach=True)


async def browse(url: str, browser: str = "") -> str:
    """Open a URL in a web browser (default, or a named one)."""
    if not url.startswith(("http://", "https://", "file://")):
        url = "https://" + url
    if browser and shutil.which(browser):
        return await _run([browser, url], detach=True)
    return await open_target(url)


async def type_text(text: str) -> str:
    """Type text into the focused window (simulated keystrokes)."""
    backend = _kbd_backend()
    if backend == "wtype":
        return await _run(["wtype", text]) or "typed"
    if backend == "xdotool":
        return await _run(["xdotool", "type", "--clearmodifiers", text]) or "typed"
    if backend == "osascript":
        esc = text.replace('"', '\\"')
        return await _run(["osascript", "-e", f'tell app "System Events" to keystroke "{esc}"']) or "typed"
    return "[no keyboard backend: install wtype (Wayland) or xdotool (X11)]"


async def press_key(combo: str) -> str:
    """Press a key or hotkey combo, e.g. 'Return', 'ctrl+c', 'ctrl+alt+t'."""
    parts = [p.strip() for p in combo.replace(" ", "").split("+") if p.strip()]
    if not parts:
        return "[empty combo]"
    *mods, key = parts
    backend = _kbd_backend()
    if backend == "wtype":
        cmd = ["wtype"]
        for m in mods:
            cmd += ["-M", m]
        cmd += ["-k", key]
        for m in reversed(mods):
            cmd += ["-m", m]
        return await _run(cmd) or f"pressed {combo}"
    if backend == "xdotool":
        return await _run(["xdotool", "key", "+".join(parts)]) or f"pressed {combo}"
    if backend == "osascript":
        return await _run(["osascript", "-e",
                           f'tell app "System Events" to keystroke "{key}"']) or f"pressed {combo}"
    return "[no keyboard backend available]"


async def screenshot(path: str = "") -> str:
    """Capture the screen to a PNG file; returns the saved path."""
    backend = _shot_backend()
    if not backend:
        return "[no screenshot backend: install grim (Wayland) or scrot (X11)]"
    SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    out = Path(path).expanduser() if path else SHOTS_DIR / f"shot-{int(time.time())}.png"
    if backend == "grim":
        await _run(["grim", str(out)])
    elif backend == "scrot":
        await _run(["scrot", str(out)])
    elif backend == "import":
        await _run(["import", "-window", "root", str(out)])
    elif backend == "screencapture":
        await _run(["screencapture", "-x", str(out)])
    return str(out) if out.exists() else f"[screenshot failed via {backend}]"


async def click(x: int = -1, y: int = -1, button: str = "left") -> str:
    """Move the mouse to (x,y) if given and click. Needs ydotool/wlrctl/xdotool."""
    backend = _click_backend()
    if not backend:
        return ("[no mouse backend. Install one: `sudo pacman -S ydotool` then "
                "`systemctl --user enable --now ydotool`, or use the browser via "
                "mcp.playwright.* for in-page clicks.]")
    if backend == "xdotool":
        if x >= 0:
            await _run(["xdotool", "mousemove", str(x), str(y)])
        btn = {"left": "1", "middle": "2", "right": "3"}.get(button, "1")
        return await _run(["xdotool", "click", btn]) or "clicked"
    if backend == "ydotool":
        if x >= 0:
            await _run(["ydotool", "mousemove", "--absolute", "-x", str(x), "-y", str(y)])
        code = {"left": "0xC0", "right": "0xC1", "middle": "0xC2"}.get(button, "0xC0")
        return await _run(["ydotool", "click", code]) or "clicked"
    if backend == "wlrctl":
        if x >= 0:
            await _run(["wlrctl", "pointer", "move", str(x), str(y)])
        return await _run(["wlrctl", "pointer", "click", button]) or "clicked"
    return "[click failed]"


async def clipboard_set(text: str) -> str:
    """Put text on the system clipboard."""
    if _IS_MAC:
        proc = await asyncio.create_subprocess_exec("pbcopy", stdin=asyncio.subprocess.PIPE)
        await proc.communicate(text.encode()); return "copied"
    if shutil.which("wl-copy"):
        proc = await asyncio.create_subprocess_exec("wl-copy", stdin=asyncio.subprocess.PIPE)
        await proc.communicate(text.encode()); return "copied"
    if shutil.which("xclip"):
        proc = await asyncio.create_subprocess_exec(
            "xclip", "-selection", "clipboard", stdin=asyncio.subprocess.PIPE)
        await proc.communicate(text.encode()); return "copied"
    return "[no clipboard backend]"


async def clipboard_get() -> str:
    """Read text from the system clipboard."""
    if _IS_MAC:
        return await _run(["pbpaste"])
    if shutil.which("wl-paste"):
        return await _run(["wl-paste"])
    if shutil.which("xclip"):
        return await _run(["xclip", "-selection", "clipboard", "-o"])
    return "[no clipboard backend]"


_DEFS = [
    ("openclaw.launch_app", launch_app, "Open a desktop app by command/name (e.g. firefox, code).",
     {"name": {"type": "string"}}, ["name"]),
    ("openclaw.open", open_target, "Open a file, folder, or URL with the default handler.",
     {"target": {"type": "string"}}, ["target"]),
    ("openclaw.browse", browse, "Open a URL in a web browser (optionally a named one).",
     {"url": {"type": "string"}, "browser": {"type": "string"}}, ["url"]),
    ("openclaw.type", type_text, "Type text into the focused window.",
     {"text": {"type": "string"}}, ["text"]),
    ("openclaw.key", press_key, "Press a key/hotkey, e.g. 'Return' or 'ctrl+t'.",
     {"combo": {"type": "string"}}, ["combo"]),
    ("openclaw.screenshot", screenshot, "Capture the screen to a PNG; returns the path.",
     {"path": {"type": "string"}}, []),
    ("openclaw.click", click, "Move mouse to (x,y) and click (needs ydotool/xdotool).",
     {"x": {"type": "integer"}, "y": {"type": "integer"}, "button": {"type": "string"}}, []),
    ("openclaw.clipboard_set", clipboard_set, "Set the clipboard text.",
     {"text": {"type": "string"}}, ["text"]),
    ("openclaw.clipboard_get", clipboard_get, "Read the clipboard text.", {}, []),
]


def register_computer_skills() -> int:
    for name, fn, desc, props, required in _DEFS:
        registry.add(Skill(
            name=name, description=desc,
            parameters={"type": "object", "properties": props, "required": required},
            handler=fn, category="computer", dangerous=True,
        ))
    return len(_DEFS)

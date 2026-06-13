"""OpenClaw extra — additional desktop-control skills for Jarvis.

Extends the core OpenClaw module (``computer.py``) with scrolling, region
screenshots, OCR, window listing/focus, paste, browser-window launch and a
chain-pause helper. Same philosophy: detect the available backend (Arch +
Wayland: wtype/grim/slurp/wl-copy; Hyprland: hyprctl; wlrctl/wmctrl where
present) and report clearly when a backend is missing instead of failing.

In-browser fine-grained control still lives in the Playwright MCP server.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import time
from pathlib import Path

from ..core.config import HOME_DIR
from .base import Skill, registry

SHOTS_DIR = HOME_DIR / "screenshots"


async def _run(cmd: list[str], timeout: int = 30) -> str:
    """Run a command, return combined stdout/stderr (never raises)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
    except FileNotFoundError:
        return f"[not found: {cmd[0]}]"
    except Exception as exc:  # noqa: BLE001
        return f"[error launching {cmd[0]}: {exc}]"
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return f"[timeout: {' '.join(cmd)}]"
    return (out or b"").decode("utf-8", "replace").strip()


def _norm_url(url: str) -> str:
    url = url.strip()
    if not url.startswith(("http://", "https://", "file://")):
        url = "https://" + url
    return url


# --- skills -----------------------------------------------------------------
async def scroll(direction: str = "down", amount: int = 3) -> str:
    """Scroll the focused window up or down."""
    direction = (direction or "down").strip().lower()
    if direction not in ("up", "down"):
        return "[scroll direction must be 'up' or 'down']"
    try:
        amount = max(1, int(amount))
    except (TypeError, ValueError):
        amount = 3

    if shutil.which("ydotool"):
        dy = -amount if direction == "up" else amount
        return await _run(["ydotool", "mousewheel", "0", str(dy)]) or f"scrolled {direction} {amount}"
    if shutil.which("wlrctl"):
        # wlrctl pointer scroll <dx> <dy>; positive dy scrolls down.
        dy = -amount * 5 if direction == "up" else amount * 5
        return await _run(["wlrctl", "pointer", "scroll", "0", str(dy)]) or f"scrolled {direction} {amount}"
    # Fall back to Page Up / Page Down via wtype.
    if shutil.which("wtype"):
        key = "Prior" if direction == "up" else "Next"
        for _ in range(amount):
            await _run(["wtype", "-k", key])
        return f"scrolled {direction} {amount} (Page {'Up' if direction == 'up' else 'Down'} via wtype)"
    return ("[no scroll backend: install ydotool or wlrctl, or wtype for "
            "Page Up/Down fallback]")


async def region_screenshot(path: str = "") -> str:
    """Interactively select a screen region and capture it to PNG; returns the path."""
    if not shutil.which("grim"):
        return "[region screenshot unavailable: install grim (sudo pacman -S grim)]"
    if not shutil.which("slurp"):
        return "[region screenshot unavailable: install slurp (sudo pacman -S slurp)]"
    geom = await _run(["slurp"])
    if not geom or geom.startswith("["):
        return f"[region selection cancelled or failed: {geom or 'no selection'}]"
    SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    out = Path(path).expanduser() if path else SHOTS_DIR / f"region-{int(time.time())}.png"
    await _run(["grim", "-g", geom, str(out)])
    return str(out) if out.exists() else "[region screenshot failed via grim]"


async def ocr(path: str = "") -> str:
    """Extract text from a screenshot (full screen if no path) via tesseract."""
    img = Path(path).expanduser() if path else None
    if img is None:
        if not shutil.which("grim"):
            return "[ocr needs a screenshot: install grim (sudo pacman -S grim)]"
        SHOTS_DIR.mkdir(parents=True, exist_ok=True)
        img = SHOTS_DIR / f"ocr-{int(time.time())}.png"
        await _run(["grim", str(img)])
        if not img.exists():
            return "[ocr failed: could not capture screenshot via grim]"
    if not img.exists():
        return f"[ocr: file not found: {img}]"
    if not shutil.which("tesseract"):
        return ("[ocr unavailable: install tesseract "
                "(sudo pacman -S tesseract tesseract-data-eng)]")
    text = await _run(["tesseract", str(img), "stdout"])
    return text or "[ocr: no text detected]"


async def windows() -> str:
    """List open windows / titles."""
    if shutil.which("wlrctl"):
        out = await _run(["wlrctl", "window", "list"])
        if out and not out.startswith("["):
            return out
    if shutil.which("hyprctl"):
        out = await _run(["hyprctl", "clients"])
        if out and not out.startswith("["):
            return out
    if shutil.which("wmctrl"):
        out = await _run(["wmctrl", "-l"])
        if out and not out.startswith("["):
            return out
    return ("[no window-list backend: install wlrctl, or use Hyprland's hyprctl, "
            "or wmctrl (X11)]")


async def focus_window(match: str) -> str:
    """Focus a window whose title matches the given substring."""
    match = (match or "").strip()
    if not match:
        return "[focus_window: provide a title substring to match]"
    if shutil.which("wlrctl"):
        out = await _run(["wlrctl", "window", "focus", match])
        return out or f"focused window matching '{match}'"
    if shutil.which("hyprctl"):
        out = await _run(["hyprctl", "dispatch", "focuswindow", f"title:{match}"])
        return out or f"focused window matching '{match}'"
    return ("[no window-focus backend: install wlrctl, or use Hyprland's "
            "hyprctl]")


async def paste() -> str:
    """Paste the clipboard into the focused window (Ctrl+V)."""
    if not shutil.which("wtype"):
        return "[paste unavailable: install wtype (sudo pacman -S wtype)]"
    return await _run(["wtype", "-M", "ctrl", "-k", "v", "-m", "ctrl"]) or "pasted (ctrl+v)"


async def run_url_in_chrome(url: str) -> str:
    """Open a URL in a NEW browser window (Chrome, else Firefox, else default)."""
    url = _norm_url(url)
    if shutil.which("google-chrome-stable"):
        cmd = ["google-chrome-stable", "--new-window", url]
    elif shutil.which("firefox"):
        cmd = ["firefox", "--new-window", url]
    elif shutil.which("xdg-open"):
        cmd = ["xdg-open", url]
    else:
        return "[no browser found: install google-chrome-stable or firefox]"
    try:
        await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            stdin=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as exc:  # noqa: BLE001
        return f"[failed to launch browser: {exc}]"
    return f"opened {url} in new window ({cmd[0]})"


async def wait(seconds: float) -> str:
    """Pause for a number of seconds (capped at 30) so UIs can settle."""
    try:
        secs = float(seconds)
    except (TypeError, ValueError):
        return "[wait: seconds must be a number]"
    secs = max(0.0, min(secs, 30.0))
    await asyncio.sleep(secs)
    return f"waited {secs:g}s"


_DEFS = [
    ("openclaw.scroll", scroll, "Scroll the focused window up or down.",
     {"direction": {"type": "string", "enum": ["up", "down"]},
      "amount": {"type": "integer"}}, ["direction"], True),
    ("openclaw.region_screenshot", region_screenshot,
     "Interactively select a screen region and capture it to PNG; returns the path.",
     {"path": {"type": "string"}}, [], True),
    ("openclaw.ocr", ocr,
     "Extract text from a screenshot (full screen if no path) via tesseract.",
     {"path": {"type": "string"}}, [], True),
    ("openclaw.windows", windows, "List open windows / titles.", {}, [], True),
    ("openclaw.focus_window", focus_window,
     "Focus a window whose title matches the given substring.",
     {"match": {"type": "string"}}, ["match"], True),
    ("openclaw.paste", paste, "Paste the clipboard into the focused window (Ctrl+V).",
     {}, [], True),
    ("openclaw.run_url_in_chrome", run_url_in_chrome,
     "Open a URL in a NEW browser window (Chrome, else Firefox, else default).",
     {"url": {"type": "string"}}, ["url"], True),
    ("openclaw.wait", wait,
     "Pause for N seconds (max 30) so UIs can settle between chained actions.",
     {"seconds": {"type": "number"}}, ["seconds"], False),
]


def register_openclaw_extra() -> int:
    for name, fn, desc, props, required, dangerous in _DEFS:
        registry.add(Skill(
            name=name, description=desc,
            parameters={"type": "object", "properties": props, "required": required},
            handler=fn, category="computer", dangerous=dangerous,
        ))
    return len(_DEFS)

"""Linux/macOS system-control skills for Jarvis.

A pack of cross-platform system-control and system-info skills: volume, mute,
brightness, battery, OS info, desktop notifications, processes, media control
and screen lock. Linux-first (Arch / Wayland / PipeWire) with macOS handled via
``osascript`` / ``pmset`` where it is easy.

Every handler is async, returns a human-readable string and never raises — CLI
tooling is run via ``asyncio.create_subprocess_exec`` and availability is probed
with ``shutil.which`` so a missing tool degrades to a clear message naming what
to install. State-changing skills are tagged ``dangerous=True``; read-only info
skills are ``dangerous=False``.
"""
from __future__ import annotations

import asyncio
import platform
import shutil
import time
from pathlib import Path

from .base import skill

_IS_MAC = platform.system() == "Darwin"
_IS_LINUX = platform.system() == "Linux"


async def _run(*args: str, timeout: float = 15) -> tuple[int, str, str]:
    """Run a command via exec; return (rc, stdout, stderr). Never raises for
    process errors — only the caller's try/except guards truly unexpected cases."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, "", f"timed out after {timeout}s"
    return (
        proc.returncode if proc.returncode is not None else -1,
        (out or b"").decode("utf-8", "replace"),
        (err or b"").decode("utf-8", "replace"),
    )


@skill(
    name="sys.volume",
    category="system",
    description="Set the system output volume to a level from 0 to 100 percent.",
    parameters={
        "type": "object",
        "properties": {
            "level": {"type": "integer", "description": "Volume 0-100 percent."}
        },
        "required": ["level"],
    },
    dangerous=True,
)
async def sys_volume(level: int) -> str:
    try:
        level = max(0, min(100, int(level)))
        if _IS_MAC:
            if not shutil.which("osascript"):
                return "[sys.volume failed: osascript not found (macOS only)]"
            rc, _, err = await _run(
                "osascript", "-e", f"set volume output volume {level}"
            )
            return f"volume set to {level}%" if rc == 0 else f"[sys.volume failed: {err.strip()}]"
        if shutil.which("wpctl"):
            rc, _, err = await _run(
                "wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{level}%"
            )
            return f"volume set to {level}%" if rc == 0 else f"[sys.volume failed: {err.strip()}]"
        if shutil.which("pactl"):
            rc, _, err = await _run(
                "pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{level}%"
            )
            return f"volume set to {level}%" if rc == 0 else f"[sys.volume failed: {err.strip()}]"
        return "[sys.volume failed: install wpctl (pipewire) or pactl (pulseaudio)]"
    except Exception as exc:
        return f"[sys.volume failed: {exc}]"


@skill(
    name="sys.mute",
    category="system",
    description="Mute or unmute the system audio output.",
    parameters={
        "type": "object",
        "properties": {
            "on": {"type": "boolean", "description": "True to mute, False to unmute."}
        },
        "required": ["on"],
    },
    dangerous=True,
)
async def sys_mute(on: bool) -> str:
    try:
        state = "muted" if on else "unmuted"
        if _IS_MAC:
            if not shutil.which("osascript"):
                return "[sys.mute failed: osascript not found (macOS only)]"
            val = "true" if on else "false"
            rc, _, err = await _run("osascript", "-e", f"set volume output muted {val}")
            return f"audio {state}" if rc == 0 else f"[sys.mute failed: {err.strip()}]"
        if shutil.which("wpctl"):
            rc, _, err = await _run(
                "wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1" if on else "0"
            )
            return f"audio {state}" if rc == 0 else f"[sys.mute failed: {err.strip()}]"
        if shutil.which("pactl"):
            rc, _, err = await _run(
                "pactl", "set-sink-mute", "@DEFAULT_SINK@", "1" if on else "0"
            )
            return f"audio {state}" if rc == 0 else f"[sys.mute failed: {err.strip()}]"
        return "[sys.mute failed: install wpctl (pipewire) or pactl (pulseaudio)]"
    except Exception as exc:
        return f"[sys.mute failed: {exc}]"


@skill(
    name="sys.volume_get",
    category="system",
    description="Get the current system output volume and mute state.",
    parameters={"type": "object", "properties": {}},
    dangerous=False,
)
async def sys_volume_get() -> str:
    try:
        if _IS_MAC:
            if not shutil.which("osascript"):
                return "[sys.volume_get failed: osascript not found (macOS only)]"
            rc, out, err = await _run(
                "osascript", "-e", "output volume of (get volume settings)"
            )
            if rc != 0:
                return f"[sys.volume_get failed: {err.strip()}]"
            return f"volume: {out.strip()}%"
        if shutil.which("wpctl"):
            rc, out, err = await _run("wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@")
            if rc != 0:
                return f"[sys.volume_get failed: {err.strip()}]"
            # e.g. "Volume: 0.55 [MUTED]"
            parts = out.split()
            pct = "?"
            if len(parts) >= 2:
                try:
                    pct = f"{round(float(parts[1]) * 100)}%"
                except ValueError:
                    pct = parts[1]
            muted = " (muted)" if "MUTED" in out.upper() else ""
            return f"volume: {pct}{muted}"
        if shutil.which("pactl"):
            rc, out, err = await _run("pactl", "get-sink-volume", "@DEFAULT_SINK@")
            if rc != 0:
                return f"[sys.volume_get failed: {err.strip()}]"
            line = out.strip().splitlines()[0] if out.strip() else out.strip()
            return f"volume: {line.strip()}"
        return "[sys.volume_get failed: install wpctl (pipewire) or pactl (pulseaudio)]"
    except Exception as exc:
        return f"[sys.volume_get failed: {exc}]"


@skill(
    name="sys.brightness",
    category="system",
    description="Set the screen backlight brightness to a percent (0-100).",
    parameters={
        "type": "object",
        "properties": {
            "percent": {"type": "integer", "description": "Brightness 0-100 percent."}
        },
        "required": ["percent"],
    },
    dangerous=True,
)
async def sys_brightness(percent: int) -> str:
    try:
        percent = max(0, min(100, int(percent)))
        if _IS_MAC:
            if shutil.which("brightness"):
                rc, _, err = await _run("brightness", f"{percent / 100:.2f}")
                return (
                    f"brightness set to {percent}%"
                    if rc == 0
                    else f"[sys.brightness failed: {err.strip()}]"
                )
            return "[sys.brightness failed: install the 'brightness' CLI (brew install brightness)]"
        if shutil.which("brightnessctl"):
            rc, _, err = await _run("brightnessctl", "set", f"{percent}%")
            return (
                f"brightness set to {percent}%"
                if rc == 0
                else f"[sys.brightness failed: {err.strip()}]"
            )
        if shutil.which("light"):
            rc, _, err = await _run("light", "-S", str(percent))
            return (
                f"brightness set to {percent}%"
                if rc == 0
                else f"[sys.brightness failed: {err.strip()}]"
            )
        if shutil.which("xbacklight"):
            rc, _, err = await _run("xbacklight", "-set", str(percent))
            return (
                f"brightness set to {percent}%"
                if rc == 0
                else f"[sys.brightness failed: {err.strip()}]"
            )
        return "[sys.brightness failed: install brightnessctl, light, or xbacklight]"
    except Exception as exc:
        return f"[sys.brightness failed: {exc}]"


@skill(
    name="sys.battery",
    category="system",
    description="Report battery charge percentage and charging state.",
    parameters={"type": "object", "properties": {}},
    dangerous=False,
)
async def sys_battery() -> str:
    try:
        if _IS_MAC:
            if not shutil.which("pmset"):
                return "[sys.battery failed: pmset not found (macOS only)]"
            rc, out, err = await _run("pmset", "-g", "batt")
            if rc != 0:
                return f"[sys.battery failed: {err.strip()}]"
            text = out.strip()
            return text.splitlines()[-1].strip() if text else "[no battery info]"
        # Linux: /sys/class/power_supply/BAT*
        bats = sorted(Path("/sys/class/power_supply").glob("BAT*"))
        if not bats:
            return "[no battery found (likely a desktop)]"
        reports = []
        for bat in bats:
            try:
                cap = (bat / "capacity").read_text().strip()
            except OSError:
                cap = "?"
            try:
                status = (bat / "status").read_text().strip()
            except OSError:
                status = "unknown"
            reports.append(f"{bat.name}: {cap}% ({status})")
        return "  ".join(reports)
    except Exception as exc:
        return f"[sys.battery failed: {exc}]"


def _fmt_bytes(n: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < 1024.0:
            return f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} PiB"


@skill(
    name="sys.info",
    category="system",
    description="Summarize OS, kernel, CPU, RAM, uptime, and root disk usage.",
    parameters={"type": "object", "properties": {}},
    dangerous=False,
)
async def sys_info() -> str:
    try:
        lines = []
        uname = platform.uname()
        lines.append(f"OS: {platform.system()} {platform.release()} ({uname.machine})")
        lines.append(f"Kernel: {uname.release}")

        # CPU model + cores
        cpu_model = platform.processor() or uname.machine
        cores = None
        if _IS_LINUX and Path("/proc/cpuinfo").exists():
            try:
                cpuinfo = Path("/proc/cpuinfo").read_text("utf-8", "replace")
                models = [
                    ln.split(":", 1)[1].strip()
                    for ln in cpuinfo.splitlines()
                    if ln.lower().startswith("model name")
                ]
                if models:
                    cpu_model = models[0]
                cores = sum(1 for ln in cpuinfo.splitlines() if ln.startswith("processor"))
            except OSError:
                pass
        if cores is None:
            try:
                import os as _os

                cores = _os.cpu_count()
            except Exception:
                cores = "?"
        lines.append(f"CPU: {cpu_model} ({cores} cores)")

        # RAM total/used via /proc/meminfo
        if _IS_LINUX and Path("/proc/meminfo").exists():
            try:
                mem = {}
                for ln in Path("/proc/meminfo").read_text().splitlines():
                    key, _, rest = ln.partition(":")
                    val = rest.strip().split()
                    if val:
                        mem[key] = int(val[0]) * 1024  # kB -> bytes
                total = mem.get("MemTotal", 0)
                avail = mem.get("MemAvailable", mem.get("MemFree", 0))
                used = total - avail
                lines.append(
                    f"RAM: {_fmt_bytes(used)} / {_fmt_bytes(total)} used"
                )
            except OSError:
                pass
        elif _IS_MAC and shutil.which("sysctl"):
            rc, out, _ = await _run("sysctl", "-n", "hw.memsize")
            if rc == 0 and out.strip().isdigit():
                lines.append(f"RAM: {_fmt_bytes(int(out.strip()))} total")

        # Uptime
        if _IS_LINUX and Path("/proc/uptime").exists():
            try:
                secs = float(Path("/proc/uptime").read_text().split()[0])
                lines.append(f"Uptime: {_fmt_duration(secs)}")
            except (OSError, ValueError):
                pass
        elif _IS_MAC and shutil.which("sysctl"):
            rc, out, _ = await _run("sysctl", "-n", "kern.boottime")
            # kern.boottime: { sec = 1234567, ... }
            try:
                sec = int(out.split("sec =")[1].split(",")[0].strip())
                lines.append(f"Uptime: {_fmt_duration(time.time() - sec)}")
            except (IndexError, ValueError):
                pass

        # Disk usage of /
        try:
            du = shutil.disk_usage("/")
            pct = (du.used / du.total * 100) if du.total else 0
            lines.append(
                f"Disk /: {_fmt_bytes(du.used)} / {_fmt_bytes(du.total)} "
                f"({pct:.0f}% used, {_fmt_bytes(du.free)} free)"
            )
        except OSError:
            pass

        return "\n".join(lines)
    except Exception as exc:
        return f"[sys.info failed: {exc}]"


def _fmt_duration(secs: float) -> str:
    secs = int(secs)
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    mins, _ = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    parts.append(f"{mins}m")
    return " ".join(parts)


@skill(
    name="sys.notify",
    category="system",
    description="Show a desktop notification with a title and message.",
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "message": {"type": "string"},
        },
        "required": ["title", "message"],
    },
    dangerous=False,
)
async def sys_notify(title: str, message: str) -> str:
    try:
        if _IS_MAC:
            if not shutil.which("osascript"):
                return "[sys.notify failed: osascript not found (macOS only)]"
            # Escape double quotes for AppleScript.
            t = title.replace('"', '\\"')
            m = message.replace('"', '\\"')
            rc, _, err = await _run(
                "osascript", "-e", f'display notification "{m}" with title "{t}"'
            )
            return "notification sent" if rc == 0 else f"[sys.notify failed: {err.strip()}]"
        if shutil.which("notify-send"):
            rc, _, err = await _run("notify-send", title, message)
            return "notification sent" if rc == 0 else f"[sys.notify failed: {err.strip()}]"
        return "[sys.notify failed: install notify-send (libnotify)]"
    except Exception as exc:
        return f"[sys.notify failed: {exc}]"


@skill(
    name="sys.processes",
    category="system",
    description="List the top processes by memory usage.",
    parameters={
        "type": "object",
        "properties": {
            "top": {"type": "integer", "description": "How many to show (default 5)."}
        },
    },
    dangerous=False,
)
async def sys_processes(top: int = 5) -> str:
    try:
        top = max(1, min(50, int(top)))
        if not shutil.which("ps"):
            return "[sys.processes failed: ps not found]"
        if _IS_MAC:
            rc, out, err = await _run("ps", "aux", "-m")
        else:
            rc, out, err = await _run("ps", "aux", "--sort=-%mem")
        if rc != 0:
            return f"[sys.processes failed: {err.strip()}]"
        rows = out.strip().splitlines()
        if not rows:
            return "[sys.processes: no output]"
        header = rows[0]
        # Columns: USER PID %CPU %MEM VSZ RSS TTY STAT START TIME COMMAND
        lines = [f"{'PID':>7}  {'%MEM':>5}  {'%CPU':>5}  COMMAND"]
        for row in rows[1 : 1 + top]:
            cols = row.split(None, 10)
            if len(cols) < 11:
                continue
            pid, cpu, mem, cmd = cols[1], cols[2], cols[3], cols[10]
            lines.append(f"{pid:>7}  {mem:>5}  {cpu:>5}  {cmd[:60]}")
        return "\n".join(lines)
    except Exception as exc:
        return f"[sys.processes failed: {exc}]"


@skill(
    name="sys.media",
    category="system",
    description="Control media playback: play, pause, play-pause, next, or previous.",
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "One of: play, pause, play-pause, next, previous, stop.",
            }
        },
        "required": ["action"],
    },
    dangerous=False,
)
async def sys_media(action: str) -> str:
    try:
        action = (action or "").strip().lower()
        aliases = {
            "play": "play",
            "pause": "pause",
            "toggle": "play-pause",
            "play-pause": "play-pause",
            "playpause": "play-pause",
            "next": "next",
            "previous": "previous",
            "prev": "previous",
            "stop": "stop",
        }
        cmd = aliases.get(action)
        if cmd is None:
            return f"[sys.media failed: unknown action '{action}'; use play/pause/next/previous]"
        if _IS_MAC:
            # No clean built-in player-control CLI; suggest playerctl is Linux-only.
            return "[sys.media failed: playerctl is Linux-only; macOS media control not supported]"
        if not shutil.which("playerctl"):
            return "[sys.media failed: install playerctl]"
        rc, out, err = await _run("playerctl", cmd)
        if rc != 0:
            msg = (err or out).strip() or "no active player"
            return f"[sys.media failed: {msg}]"
        return f"media: {cmd}"
    except Exception as exc:
        return f"[sys.media failed: {exc}]"


@skill(
    name="sys.lock",
    category="system",
    description="Lock the screen / current session.",
    parameters={"type": "object", "properties": {}},
    dangerous=True,
)
async def sys_lock() -> str:
    try:
        if _IS_MAC:
            if shutil.which("pmset"):
                rc, _, err = await _run("pmset", "displaysleepnow")
                return "screen locked" if rc == 0 else f"[sys.lock failed: {err.strip()}]"
            return "[sys.lock failed: pmset not found (macOS only)]"
        if shutil.which("loginctl"):
            rc, _, err = await _run("loginctl", "lock-session")
            if rc == 0:
                return "session locked"
            # Fall through to a dedicated locker if loginctl can't determine session.
            last_err = err.strip()
        else:
            last_err = "loginctl not found"
        for locker, args in (
            ("loginctl", None),
            ("swaylock", []),
            ("hyprlock", []),
            ("i3lock", []),
            ("xdg-screensaver", ["lock"]),
        ):
            if locker == "loginctl":
                continue
            if shutil.which(locker):
                rc, _, err = await _run(locker, *(args or []))
                if rc == 0:
                    return f"screen locked ({locker})"
                last_err = err.strip() or last_err
        return f"[sys.lock failed: {last_err}; install loginctl/swaylock/hyprlock/i3lock]"
    except Exception as exc:
        return f"[sys.lock failed: {exc}]"


@skill(
    name="sys.sleep",
    category="system",
    description="Suspend / sleep the system (S3 sleep / hibernate).",
    parameters={
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["suspend", "hibernate", "hybrid-sleep"],
                "description": "Sleep mode. Default: suspend (RAM sleep, fastest resume).",
            }
        },
    },
    dangerous=True,
)
async def sys_sleep(mode: str = "suspend") -> str:
    try:
        if _IS_MAC:
            rc, _, err = await _run("pmset", "sleepnow")
            return "system sleeping" if rc == 0 else f"[sys.sleep failed: {err.strip()}]"
        allowed = {"suspend", "hibernate", "hybrid-sleep"}
        m = mode if mode in allowed else "suspend"
        if shutil.which("systemctl"):
            rc, _, err = await _run("systemctl", m)
            return f"system {m}" if rc == 0 else f"[sys.sleep failed: {err.strip()}]"
        if shutil.which("pm-suspend") and m == "suspend":
            rc, _, err = await _run("pm-suspend")
            return "system suspend" if rc == 0 else f"[sys.sleep failed: {err.strip()}]"
        return "[sys.sleep failed: systemctl not found]"
    except Exception as exc:
        return f"[sys.sleep failed: {exc}]"


# Number of skills registered above via @skill on import.
_SKILL_COUNT = 10


def register_system_skills() -> int:
    """All skills here auto-register via the @skill decorator on import.

    Returns the count of system-control skills registered by this module.
    """
    return _SKILL_COUNT

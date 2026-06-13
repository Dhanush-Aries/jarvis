"""Install Jarvis as an always-on background voice service.

Linux  -> systemd *user* service (no root): auto-starts `jarvis voice` at login,
          restarts on failure. `loginctl enable-linger` makes it survive logout /
          start at boot.
macOS   -> launchd LaunchAgent.
Other   -> prints manual instructions.

Exposed via `jarvis service install|status|uninstall|logs`.
"""
from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path

UNIT_NAME = "jarvis-voice.service"
PLIST_LABEL = "com.jarvis.voice"


def _jarvis_bin() -> str:
    cand = Path(sys.executable).parent / "jarvis"
    return str(cand) if cand.exists() else "jarvis"


def _repo_dir() -> str:
    return str(Path(__file__).resolve().parents[2])


# ---------------------------------------------------------------- systemd (Linux)
def _systemd_unit() -> str:
    return f"""[Unit]
Description=Jarvis always-on voice assistant
After=default.target sound.target pipewire.service
Wants=pipewire.service

[Service]
Type=simple
ExecStart={_jarvis_bin()} voice
WorkingDirectory={_repo_dir()}
Environment=PYTHONUNBUFFERED=1
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
"""


def _systemctl(*args: str) -> tuple[int, str]:
    proc = subprocess.run(["systemctl", "--user", *args],
                          capture_output=True, text=True)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def _install_systemd() -> str:
    unit_dir = Path(os.path.expanduser("~/.config/systemd/user"))
    unit_dir.mkdir(parents=True, exist_ok=True)
    (unit_dir / UNIT_NAME).write_text(_systemd_unit(), encoding="utf-8")
    out = [f"wrote {unit_dir / UNIT_NAME}"]
    for args in (["daemon-reload"], ["enable", "--now", UNIT_NAME]):
        rc, msg = _systemctl(*args)
        out.append(f"systemctl --user {' '.join(args)} -> {'ok' if rc == 0 else msg}")
    # Best-effort: keep it running across logout / from boot.
    linger = subprocess.run(["loginctl", "enable-linger", os.environ.get("USER", "")],
                            capture_output=True, text=True)
    out.append("linger enabled" if linger.returncode == 0
               else "linger not enabled (run: sudo loginctl enable-linger $USER)")
    out.append("\nJarvis voice is now always-on. Check: jarvis service status")
    return "\n".join(out)


def _status_systemd() -> str:
    rc, msg = _systemctl("is-active", UNIT_NAME)
    rc2, msg2 = _systemctl("is-enabled", UNIT_NAME)
    return f"active: {msg}\nenabled: {msg2}\nlogs: jarvis service logs"


def _uninstall_systemd() -> str:
    out = []
    for args in (["disable", "--now", UNIT_NAME],):
        _rc, msg = _systemctl(*args)
        out.append(f"systemctl --user {' '.join(args)} -> {msg or 'ok'}")
    unit = Path(os.path.expanduser("~/.config/systemd/user")) / UNIT_NAME
    if unit.exists():
        unit.unlink()
        out.append(f"removed {unit}")
    _systemctl("daemon-reload")
    return "\n".join(out)


def _logs_systemd() -> str:
    proc = subprocess.run(
        ["journalctl", "--user", "-u", UNIT_NAME, "-n", "40", "--no-pager"],
        capture_output=True, text=True)
    return (proc.stdout + proc.stderr).strip() or "(no logs yet)"


# ---------------------------------------------------------------- launchd (macOS)
def _plist() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{PLIST_LABEL}</string>
  <key>ProgramArguments</key><array>
    <string>{_jarvis_bin()}</string><string>voice</string></array>
  <key>WorkingDirectory</key><string>{_repo_dir()}</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict></plist>
"""


def _install_launchd() -> str:
    path = Path(os.path.expanduser(f"~/Library/LaunchAgents/{PLIST_LABEL}.plist"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_plist(), encoding="utf-8")
    subprocess.run(["launchctl", "unload", str(path)], capture_output=True)
    rc = subprocess.run(["launchctl", "load", str(path)], capture_output=True, text=True)
    return f"wrote {path}\nlaunchctl load -> {'ok' if rc.returncode == 0 else rc.stderr}"


# ---------------------------------------------------------------- dispatch
def manage(action: str) -> str:
    system = platform.system()
    if system == "Linux":
        if action == "install":
            return _install_systemd()
        if action == "status":
            return _status_systemd()
        if action == "uninstall":
            return _uninstall_systemd()
        if action == "logs":
            return _logs_systemd()
    elif system == "Darwin":
        if action == "install":
            return _install_launchd()
        return f"On macOS, manage with: launchctl (label {PLIST_LABEL})"
    else:
        return ("Always-on service is supported on Linux (systemd) and macOS "
                "(launchd). On Windows, create a Task Scheduler task running "
                f"`{_jarvis_bin()} voice` at logon.")
    return f"unknown action '{action}' (use install|status|uninstall|logs)"

"""GUI vision-control skills — the "Jarvis sees the screen and acts" loop.

  gui.observe(question)  — screenshot the screen and answer a question about it.
  gui.do(goal, max_steps) — iteratively screenshot → a vision model decides the
                            next action (click/type/key/scroll/done) → OpenClaw
                            executes it → repeat until the goal is met.

Works with any provider via providers/vision.py. Clicking needs a mouse backend
(ydotool/wlrctl/xdotool); without it the loop still drives the keyboard and
reports that clicks are unavailable.
"""
from __future__ import annotations

import json
import re

from ..core.capabilities import probe
from ..core.config import load_settings
from ..providers import vision
from . import computer
from .base import Skill, registry

_ACTION_PROTOCOL = (
    "You are controlling a desktop by looking at screenshots. Decide the SINGLE "
    "next action toward the goal and reply with ONLY a JSON object:\n"
    '{"action":"click|type|key|done","x":<int>,"y":<int>,"text":"<for type>",'
    '"keys":"<for key, e.g. ctrl+t or Return>","reason":"<short>"}\n'
    "Use pixel coordinates from the screenshot for click. Use 'done' when the "
    "goal is achieved (put the outcome in reason)."
)


def _parse_action(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return {"action": "done", "reason": text[:200]}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {"action": "done", "reason": text[:200]}


async def observe(question: str = "Describe what is on the screen.") -> str:
    settings = load_settings()
    caps = probe(settings)
    shot = await computer.screenshot()
    if shot.startswith("["):
        return shot
    return await vision.see(shot, question, caps, settings)


async def do(goal: str, max_steps: int = 6) -> str:
    settings = load_settings()
    caps = probe(settings)
    log: list[str] = [f"goal: {goal}"]
    for step in range(1, max_steps + 1):
        shot = await computer.screenshot()
        if shot.startswith("["):
            return shot
        answer = await vision.see(
            shot, f"Goal: {goal}\n{_ACTION_PROTOCOL}", caps, settings)
        act = _parse_action(answer)
        kind = act.get("action", "done")
        reason = act.get("reason", "")
        log.append(f"step {step}: {kind} ({reason})")
        if kind == "done":
            break
        if kind == "click":
            res = await computer.click(int(act.get("x", -1)), int(act.get("y", -1)),
                                       act.get("button", "left"))
            log.append(f"  click -> {res}")
            if res.startswith("[no mouse backend"):
                log.append("  (install ydotool for mouse control)")
                break
        elif kind == "type":
            log.append(f"  type -> {await computer.type_text(act.get('text', ''))}")
        elif kind == "key":
            log.append(f"  key -> {await computer.press_key(act.get('keys', ''))}")
        else:
            break
    return "\n".join(log)


def register_gui_skills() -> int:
    defs = [
        ("gui.observe", observe, "Screenshot the screen and answer a question about what's shown.",
         {"question": {"type": "string"}}, []),
        ("gui.do", do, "Achieve a GUI goal by looping: see the screen -> act -> repeat.",
         {"goal": {"type": "string"}, "max_steps": {"type": "integer"}}, ["goal"]),
    ]
    for name, fn, desc, props, required in defs:
        registry.add(Skill(
            name=name, description=desc,
            parameters={"type": "object", "properties": props, "required": required},
            handler=fn, category="computer", dangerous=True,
        ))
    return len(defs)

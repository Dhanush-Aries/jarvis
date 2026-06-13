"""Long-term memory + self-scheduling skills.

These give Jarvis a persistent brain (remember/recall facts across sessions) and
the ability to schedule its own future tasks for the daemon to run. Each opens a
short-lived SQLite connection, so they're decoupled from any running kernel.
"""
from __future__ import annotations

import re

from ..memory.store import MemoryStore
from .base import Skill, registry


async def remember(key: str, value: str, tags: str = "") -> str:
    store = await MemoryStore.open()
    try:
        await store.remember(key, value, tags)
        return f"remembered '{key}'"
    finally:
        await store.close()


async def recall(query: str) -> str:
    store = await MemoryStore.open()
    try:
        hits = await store.recall(query)
        if not hits:
            return "[no relevant memories]"
        return "\n".join(f"- {h['key']}: {h['value']}" for h in hits)
    finally:
        await store.close()


async def schedule_add(name: str, cron: str, prompt: str) -> str:
    """Schedule a recurring task. cron is standard 5-field crontab syntax."""
    if not re.match(r"^[\d*/,\- ]+$", cron) or len(cron.split()) != 5:
        return "[invalid cron: use 5 fields, e.g. '0 9 * * *' for 9am daily]"
    store = await MemoryStore.open()
    try:
        job_id = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "job"
        await store.conn.execute(
            "INSERT OR REPLACE INTO scheduled_jobs(id, name, cron, prompt, enabled) "
            "VALUES (?,?,?,?,1)",
            (job_id, name, cron, prompt),
        )
        await store.conn.commit()
        return f"scheduled '{name}' ({cron}) as job '{job_id}'. Run `jarvis daemon` to activate."
    finally:
        await store.close()


async def schedule_list() -> str:
    store = await MemoryStore.open()
    try:
        cur = await store.conn.execute(
            "SELECT id, name, cron, enabled FROM scheduled_jobs ORDER BY id"
        )
        rows = await cur.fetchall()
        if not rows:
            return "[no scheduled jobs]"
        return "\n".join(
            f"- {r['id']}: {r['name']} [{r['cron']}] {'on' if r['enabled'] else 'off'}"
            for r in rows
        )
    finally:
        await store.close()


_DEFS = [
    ("memory.remember", remember, "Persist a fact to long-term memory across sessions.",
     {"key": {"type": "string"}, "value": {"type": "string"}, "tags": {"type": "string"}},
     ["key", "value"], False),
    ("memory.recall", recall, "Search long-term memory for facts relevant to a query.",
     {"query": {"type": "string"}}, ["query"], False),
    ("schedule.add", schedule_add, "Schedule a recurring task (5-field cron) for the daemon.",
     {"name": {"type": "string"}, "cron": {"type": "string"}, "prompt": {"type": "string"}},
     ["name", "cron", "prompt"], True),
    ("schedule.list", schedule_list, "List scheduled tasks.", {}, [], False),
]


def register_memory_skills() -> int:
    for name, fn, desc, props, required, dangerous in _DEFS:
        registry.add(Skill(
            name=name, description=desc,
            parameters={"type": "object", "properties": props, "required": required},
            handler=fn, category="general", dangerous=dangerous,
        ))
    return len(_DEFS)

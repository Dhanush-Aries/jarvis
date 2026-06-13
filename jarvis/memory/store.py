"""High-level memory operations over the SQLite connection."""
from __future__ import annotations

from typing import Any

import aiosqlite

from . import db


class MemoryStore:
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self.conn = conn

    @classmethod
    async def open(cls) -> "MemoryStore":
        return cls(await db.connect())

    async def close(self) -> None:
        await self.conn.close()

    # --- conversation history --------------------------------------------------
    async def add_message(
        self, session_id: str, role: str, content: str,
        agent: str | None = None, model: str | None = None,
    ) -> None:
        await self.conn.execute(
            "INSERT INTO conversations(session_id, role, content, agent, model) "
            "VALUES (?,?,?,?,?)",
            (session_id, role, content, agent, model),
        )
        await self.conn.commit()

    async def history(self, session_id: str, limit: int = 20) -> list[dict[str, str]]:
        cur = await self.conn.execute(
            "SELECT role, content FROM conversations WHERE session_id=? "
            "ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        )
        rows = await cur.fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    # --- audit journal ---------------------------------------------------------
    async def journal(
        self, action: str, detail: str = "", status: str = "ok",
        session_id: str | None = None, agent: str | None = None,
    ) -> None:
        await self.conn.execute(
            "INSERT INTO task_journal(session_id, agent, action, detail, status) "
            "VALUES (?,?,?,?,?)",
            (session_id, agent, action, detail, status),
        )
        await self.conn.commit()

    async def recent_journal(self, limit: int = 50) -> list[dict[str, Any]]:
        cur = await self.conn.execute(
            "SELECT * FROM task_journal ORDER BY id DESC LIMIT ?", (limit,)
        )
        return [dict(r) for r in await cur.fetchall()]

    # --- long-term memory (FTS5) ----------------------------------------------
    async def remember(self, key: str, value: str, tags: str = "") -> None:
        await self.conn.execute(
            "INSERT INTO longterm(key, value, tags) VALUES (?,?,?)", (key, value, tags)
        )
        await self.conn.commit()

    async def recall(self, query: str, limit: int = 5) -> list[dict[str, str]]:
        # FTS5 ANDs multiple bare terms, which makes a raw sentence almost never
        # match. Build an OR of sanitized word-tokens (>=3 chars) instead.
        import re

        terms = [t for t in re.findall(r"[A-Za-z0-9]+", query) if len(t) >= 3]
        if not terms:
            return []
        match = " OR ".join(terms)
        try:
            cur = await self.conn.execute(
                "SELECT key, value FROM longterm WHERE longterm MATCH ? "
                "ORDER BY rank LIMIT ?",
                (match, limit),
            )
            return [dict(r) for r in await cur.fetchall()]
        except Exception:
            return []

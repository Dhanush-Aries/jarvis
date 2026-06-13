"""Always-on daemon: runs scheduled jobs from the DB and an autonomous tick.

Optional: requires the 'daemon' extra (APScheduler). Jobs are stored in
scheduled_jobs; each fires a prompt through the kernel in autonomous mode.
"""
from __future__ import annotations

import asyncio

from ...core.context import RequestContext
from ...core.kernel import Kernel


async def run_daemon() -> None:
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger
    except Exception as exc:  # pragma: no cover
        raise SystemExit(
            "Daemon extra not installed. Run: pip install 'jarvis-assistant[daemon]'"
        ) from exc

    kernel = await Kernel.create()
    scheduler = AsyncIOScheduler()

    async def fire(prompt: str, job_id: str) -> None:
        await kernel.memory.journal("scheduled_fire", detail=job_id)
        resp = await kernel.handle(RequestContext(
            text=prompt, source="daemon", session_id=f"job:{job_id}", autonomous=True
        ))
        await kernel.memory.journal("scheduled_done", detail=(resp.text or "")[:200])

    # Load enabled jobs from the DB.
    cur = await kernel.memory.conn.execute(
        "SELECT id, name, cron, prompt FROM scheduled_jobs WHERE enabled=1"
    )
    rows = await cur.fetchall()
    for r in rows:
        try:
            scheduler.add_job(
                fire, CronTrigger.from_crontab(r["cron"]),
                args=[r["prompt"], r["id"]], id=r["id"], replace_existing=True,
            )
        except Exception:
            continue

    scheduler.start()
    print(f"[daemon] running with {len(rows)} scheduled job(s). Ctrl-C to stop.")
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        scheduler.shutdown(wait=False)
        await kernel.close()

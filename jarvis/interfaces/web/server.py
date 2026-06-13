"""FastAPI dashboard: chat endpoint + capability/journal views + static UI.

Optional: requires the 'web' extra. `serve()` errors cleanly if FastAPI/uvicorn
are not installed.
"""
from __future__ import annotations

from pathlib import Path

STATIC_DIR = Path(__file__).parent / "static"


def build_app():
    try:
        from fastapi import FastAPI
        from fastapi.responses import FileResponse, JSONResponse
        from fastapi.staticfiles import StaticFiles
        from pydantic import BaseModel
    except Exception as exc:  # pragma: no cover
        raise SystemExit(
            "Web extra not installed. Run: pip install 'jarvis-assistant[web]'"
        ) from exc

    from ...core.context import RequestContext
    from ...core.kernel import Kernel

    app = FastAPI(title="Jarvis")
    state: dict[str, Kernel] = {}

    class Ask(BaseModel):
        text: str
        session_id: str = "web"
        agent: str | None = None

    @app.on_event("startup")
    async def _startup() -> None:
        state["kernel"] = await Kernel.create()

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        if "kernel" in state:
            await state["kernel"].close()

    @app.get("/api/health")
    async def health():
        k = state["kernel"]
        return JSONResponse({"capabilities": k.caps.as_dict(), "skills": k.skill_stats()})

    @app.get("/api/journal")
    async def journal():
        k = state["kernel"]
        return JSONResponse(await k.memory.recent_journal())

    @app.post("/api/ask")
    async def ask(body: Ask):
        k = state["kernel"]
        resp = await k.handle(RequestContext(
            text=body.text, source="web", session_id=body.session_id, agent_hint=body.agent
        ))
        return JSONResponse({
            "text": resp.text, "agent": resp.agent, "model": resp.model,
            "steps": resp.steps, "error": resp.error,
        })

    @app.get("/")
    async def index():
        return FileResponse(STATIC_DIR / "index.html")

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


def serve(host: str | None = None, port: int | None = None) -> None:
    import uvicorn

    from ...core.config import load_settings

    settings = load_settings()
    host = host or settings.web.get("host", "127.0.0.1")
    port = port or int(settings.web.get("port", 8787))
    uvicorn.run(build_app(), host=host, port=port)

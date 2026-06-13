"""The interface-agnostic kernel. Every frontend goes through Kernel.handle()."""
from __future__ import annotations

import re

from ..agents.registry import route
from ..memory.store import MemoryStore
from ..providers.router import NoUsableModelError, Router
from ..skills.loader import load_all_skills
from .capabilities import CapabilityReport, probe
from .config import Settings, load_settings
from .context import RequestContext, Response


class Kernel:
    def __init__(self, settings: Settings, caps: CapabilityReport,
                 router: Router, memory: MemoryStore) -> None:
        self.settings = settings
        self.caps = caps
        self.router = router
        self.memory = memory
        self._skill_stats: dict[str, int] = {}

    @classmethod
    async def create(cls, config_path: str | None = None, with_mcp: bool = True) -> "Kernel":
        settings = load_settings(config_path)
        caps = probe(settings)
        router = Router(settings, caps)
        memory = await MemoryStore.open()
        stats = await load_all_skills(settings, with_mcp=with_mcp)
        kernel = cls(settings, caps, router, memory)
        kernel._skill_stats = stats
        return kernel

    async def handle(self, ctx: RequestContext) -> Response:
        if not self.caps.has_any_provider:
            return Response(
                error="No LLM provider available. Set an API key (e.g. ANTHROPIC_API_KEY) "
                "or run Ollama: `ollama serve && ollama pull llama3.1`.",
                text="I can't reach any model right now.",
            )
        history = await self.memory.history(ctx.session_id)
        # Auto-recall: surface relevant long-term memories to the agent.
        recalled = await self.memory.recall(ctx.text)
        if recalled:
            facts = "; ".join(f"{r['key']}: {r['value']}" for r in recalled)
            history = [{"role": "system", "content": f"Relevant memory — {facts}"}, *history]
        # Spoken replies must be short and natural — this is read aloud.
        if ctx.source == "voice":
            history = [{"role": "system", "content": "This reply will be SPOKEN aloud. "
                        "Answer in ONE or two short sentences, conversational, no lists "
                        "or markdown. Confirm actions crisply, like JARVIS."}, *history]
        agent = await route(ctx, self.router)
        await self.memory.add_message(ctx.session_id, "user", ctx.text)
        await self.memory.journal("dispatch", detail=f"agent={agent.name}",
                                  session_id=ctx.session_id, agent=agent.name)
        try:
            resp = await agent.run(ctx, self.router, self.settings, history)
        except NoUsableModelError as exc:
            return Response(agent=agent.name, error=str(exc),
                            text="Every model in the chain failed — try again or check provider keys.")
        except Exception as exc:  # never let a model/tool error crash the frontend
            await self.memory.journal("error", detail=str(exc)[:200],
                                      session_id=ctx.session_id, agent=agent.name, status="error")
            return Response(agent=agent.name, error=str(exc),
                            text="Something went wrong handling that request.")
        if resp.text:
            await self.memory.add_message(
                ctx.session_id, "assistant", resp.text, agent=resp.agent, model=resp.model
            )
        await self._auto_learn(ctx.text)
        for step in resp.steps:
            await self.memory.journal(
                "tool", detail=f"{step['skill']} {step.get('args')}",
                session_id=ctx.session_id, agent=resp.agent,
            )
        return resp

    # Patterns that signal a durable fact worth remembering (the "soul" grows).
    _LEARN = re.compile(
        r"\b(my name is|i am|i'm|i like|i prefer|i use|i live in|i work|"
        r"remember that|note that|call me|my favorite|my favourite)\b[^.?!\n]{2,80}",
        re.I)

    async def _auto_learn(self, text: str) -> None:
        try:
            for m in self._LEARN.finditer(text or ""):
                fact = m.group(0).strip()
                existing = await self.memory.recall(fact)
                if not any(fact.lower() == e["value"].lower() for e in existing):
                    await self.memory.remember(f"user-said-{abs(hash(fact)) % 100000}",
                                               fact, tags="auto,preference")
        except Exception:
            pass

    async def close(self) -> None:
        try:
            from ..providers import claude_sdk

            for sess in list(claude_sdk._pool.values()):
                await sess.close()
            claude_sdk._pool.clear()
        except Exception:
            pass
        await self.memory.close()

    def skill_stats(self) -> dict[str, int]:
        return self._skill_stats

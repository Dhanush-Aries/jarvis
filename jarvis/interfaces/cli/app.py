"""Rich-powered terminal chat frontend."""
from __future__ import annotations

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from ...core.context import RequestContext
from ...core.kernel import Kernel

console = Console()


def _render(resp) -> None:
    if resp.error:
        console.print(Panel(resp.error, title="error", border_style="red"))
        return
    header = f"[bold cyan]jarvis[/] [dim]({resp.agent} · {resp.model})[/]"
    console.print(header)
    if resp.steps:
        for s in resp.steps:
            console.print(f"  [dim]· {s['skill']}[/]")
    console.print(Markdown(resp.text or "(no output)"))
    console.print()


async def one_shot(text: str, session: str = "default", agent: str | None = None,
                   autonomous: bool | None = None, with_mcp: bool = True) -> None:
    kernel = await Kernel.create(with_mcp=with_mcp)
    try:
        resp = await kernel.handle(
            RequestContext(text=text, source="cli", session_id=session,
                           agent_hint=agent, autonomous=autonomous)
        )
        _render(resp)
    finally:
        await kernel.close()


async def chat_loop(session: str = "default", with_mcp: bool = True) -> None:
    kernel = await Kernel.create(with_mcp=with_mcp)
    stats = kernel.skill_stats()
    caps = kernel.caps
    providers = ", ".join(caps.providers) or ("ollama" if caps.ollama else "none")
    console.print(Panel.fit(
        f"[bold cyan]JARVIS[/] online\n"
        f"providers: [green]{providers}[/]   skills: [green]{stats.get('total', 0)}[/]   "
        f"mode: [yellow]{'autonomous' if kernel.settings.autonomous else 'approval'}[/]\n"
        f"[dim]type 'exit' to quit, '/agent <name>' to force an agent[/]",
        border_style="cyan",
    ))
    forced: str | None = None
    try:
        while True:
            try:
                text = console.input("[bold green]you ›[/] ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not text:
                continue
            if text in ("exit", "quit", ":q"):
                break
            if text.startswith("/agent "):
                forced = text.split(" ", 1)[1].strip() or None
                console.print(f"[dim]forcing agent: {forced}[/]")
                continue
            with console.status("[cyan]thinking…[/]"):
                resp = await kernel.handle(
                    RequestContext(text=text, source="cli", session_id=session,
                                   agent_hint=forced)
                )
            _render(resp)
    finally:
        await kernel.close()
        console.print("[dim]jarvis offline.[/]")

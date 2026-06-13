"""Jarvis CLI entrypoint (typer)."""
from __future__ import annotations

import asyncio
import json

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(add_completion=False, help="Jarvis — your autonomous AI assistant.")
console = Console()


@app.command()
def chat(
    session: str = typer.Option("default", help="Conversation/session id."),
    no_mcp: bool = typer.Option(False, "--no-mcp", help="Skip MCP tool discovery (faster start)."),
) -> None:
    """Start an interactive chat (the default Jarvis experience)."""
    from .interfaces.cli import chat_loop

    asyncio.run(chat_loop(session=session, with_mcp=not no_mcp))


@app.command()
def ask(
    prompt: list[str] = typer.Argument(..., help="The request."),
    agent: str = typer.Option(None, help="Force agent: chat|coding|hacking|automation|openclaw|hermes."),
    session: str = typer.Option("default", help="Conversation/session id (for memory continuity)."),
    autonomous: bool = typer.Option(None, "--autonomous/--approve",
                                    help="Override config: full-auto vs ask-before-acting."),
    no_mcp: bool = typer.Option(False, "--no-mcp"),
) -> None:
    """One-shot request, print the answer, exit."""
    from .interfaces.cli import one_shot

    asyncio.run(one_shot(" ".join(prompt), agent=agent, session=session,
                         autonomous=autonomous, with_mcp=not no_mcp))


@app.command()
def doctor() -> None:
    """Show the capability report: providers, voice, tools, skills."""
    from .core.capabilities import probe
    from .core.config import load_settings

    settings = load_settings()
    caps = probe(settings)
    t = Table(title="Jarvis capability report", show_header=False)
    for k, v in caps.as_dict().items():
        t.add_row(str(k), json.dumps(v) if not isinstance(v, str) else v)
    console.print(t)
    if not caps.has_any_provider:
        console.print("[red]No provider![/] Set an API key or run: ollama serve && "
                      "ollama pull llama3.1")


@app.command()
def skills(no_mcp: bool = typer.Option(False, "--no-mcp")) -> None:
    """List all registered skills."""
    from .core.config import load_settings
    from .skills.loader import load_all_skills
    from .skills.base import registry

    settings = load_settings()
    stats = asyncio.run(load_all_skills(settings, with_mcp=not no_mcp))
    t = Table(title=f"Skills ({stats['total']})")
    t.add_column("name", style="cyan")
    t.add_column("category")
    t.add_column("description")
    for s in sorted(registry.all(), key=lambda x: x.name):
        t.add_row(s.name, s.category, (s.description or "")[:60])
    console.print(t)


@app.command()
def web(
    host: str = typer.Option(None, help="Bind host (default from config)."),
    port: int = typer.Option(None, help="Bind port (default from config)."),
) -> None:
    """Launch the local web dashboard (requires the 'web' extra)."""
    from .interfaces.web.server import serve

    serve(host=host, port=port)


@app.command()
def daemon() -> None:
    """Run the background daemon for scheduled/autonomous tasks (requires 'daemon' extra)."""
    from .interfaces.daemon.runner import run_daemon

    asyncio.run(run_daemon())


@app.command()
def voice() -> None:
    """Launch the voice interface (requires the 'voice' extra + a microphone)."""
    from .interfaces.voice_app.app import run_voice

    asyncio.run(run_voice())


@app.command()
def service(
    action: str = typer.Argument("status", help="install | status | uninstall | logs"),
) -> None:
    """Manage the always-on background voice service (systemd/launchd)."""
    from .interfaces.service import manage

    console.print(manage(action))


@app.command()
def reactor(
    port: int = typer.Option(8788, help="Local port for the reactor UI."),
    no_open: bool = typer.Option(False, "--no-open", help="Don't auto-open the browser."),
) -> None:
    """Open the spinning arc-reactor UI that reacts to Jarvis's voice state."""
    from .interfaces.reactor import run_reactor

    run_reactor(port=port, open_browser=not no_open)


@app.command()
def popup(
    port: int = typer.Option(8789, help="Local port for the popup server."),
    no_open: bool = typer.Option(False, "--no-open", help="Don't auto-launch Chrome."),
) -> None:
    """Open a Siri-style floating popup that reacts to Jarvis's voice state."""
    from .interfaces.popup import run_popup

    run_popup(port=port, open_browser=not no_open)


if __name__ == "__main__":
    app()

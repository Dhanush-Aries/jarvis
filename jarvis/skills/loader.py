"""One call to populate the skill registry from all sources."""
from __future__ import annotations

from ..core.config import Settings
from . import builtins as _builtins  # noqa: F401  (import triggers @skill registration)
from . import system_ctl as _system_ctl  # noqa: F401  (@skill registration on import)
from . import trading as _trading  # noqa: F401  (import triggers @skill registration)
from . import web_apis as _web_apis  # noqa: F401  (import triggers @skill registration)
from . import web_apis2 as _web_apis2  # noqa: F401  (import triggers @skill registration)
from .base import load_plugins, registry
from .claude_bridge import register_claude_skills
from .computer import register_computer_skills
from .gui import register_gui_skills
from .mcp_bridge import register_mcp_skills
from .memory_skills import register_memory_skills
from .openclaw_extra import register_openclaw_extra
from .project_bridge import register_project_skills


async def load_all_skills(settings: Settings, with_mcp: bool = True) -> dict[str, int]:
    """Register builtins, plugins, project bridges, and (optionally) MCP tools."""
    before = len(registry.all())
    plugins = load_plugins()
    projects = register_project_skills()
    claude = register_claude_skills()
    computer = register_computer_skills()
    openclaw_x = register_openclaw_extra()
    gui = register_gui_skills()
    mem = register_memory_skills()
    mcp = await register_mcp_skills(settings) if with_mcp else 0
    return {
        "builtins": before,
        "plugins": plugins,
        "projects": projects,
        "claude_code": claude,
        "computer": computer + openclaw_x,
        "gui": gui,
        "memory": mem,
        "mcp": mcp,
        "total": len(registry.all()),
    }

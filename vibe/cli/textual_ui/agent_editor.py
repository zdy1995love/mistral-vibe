from __future__ import annotations

from pathlib import Path

from vibe.core.agents.manager import AgentManager
from vibe.core.agents.models import BUILTIN_AGENTS, AgentProfile, AgentType
from vibe.core.config.harness_files import get_harness_files_manager
from vibe.core.paths import VIBE_HOME


class AgentEditorError(RuntimeError):
    pass


def resolve_edit_path(name: str, manager: AgentManager) -> Path:
    """Return the filesystem path to edit for an agent.

    For agents loaded from a TOML on disk, returns that file. For a builtin
    with no on-disk override yet, creates a starter override at
    `VIBE_HOME/agents/<name>.toml` and returns that path. Raises
    `AgentEditorError` if user-level writes are disabled (project-only
    sources), the agent is unknown, or the agent is custom but has no
    on-disk TOML (which should be impossible if `manager` is consistent).
    """
    on_disk = _find_on_disk_toml(name, manager)
    if on_disk is not None:
        return on_disk
    if name not in BUILTIN_AGENTS:
        raise AgentEditorError(
            f"Agent '{name}' has no on-disk TOML and is not a builtin."
        )
    try:
        profile = manager.get_agent(name)
    except ValueError as e:
        raise AgentEditorError(str(e)) from e
    return _create_override_stub(profile)


def _find_on_disk_toml(name: str, manager: AgentManager) -> Path | None:
    for base in manager._search_paths:  # pyright: ignore[reportPrivateUsage]
        candidate = base / f"{name}.toml"
        if candidate.is_file():
            return candidate
    return None


def _create_override_stub(profile: AgentProfile) -> Path:
    mgr = get_harness_files_manager()
    if "user" not in mgr.sources:
        raise AgentEditorError(
            "User-level agents directory is disabled (project-only sources)."
        )
    target_dir = VIBE_HOME.path / "agents"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{profile.name}.toml"
    target.write_text(_starter_toml(profile))
    return target


def _starter_toml(profile: AgentProfile) -> str:
    lines = [
        f"# Override for builtin agent '{profile.name}'.",
        "# Edit fields below; remove this file to revert to the builtin.",
        f"description = {profile.description!r}",
        f"safety = '{profile.safety.value}'",
    ]
    if profile.agent_type != AgentType.AGENT:
        lines.append(f"agent_type = '{profile.agent_type.value}'")
    lines.append("")
    return "\n".join(lines)

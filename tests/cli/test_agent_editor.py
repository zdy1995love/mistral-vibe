from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import build_test_vibe_config
from vibe.cli.textual_ui.agent_editor import AgentEditorError, resolve_edit_path
from vibe.core.agents.manager import AgentManager
from vibe.core.agents.models import BUILTIN_AGENTS


@pytest.fixture
def manager_with_custom_agent(tmp_path: Path) -> tuple[AgentManager, Path]:
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    toml_path = agents_dir / "my-custom.toml"
    toml_path.write_text("description = 'Mine'\nsafety = 'neutral'\n")
    config = build_test_vibe_config(
        agent_paths=[agents_dir],
        include_project_context=False,
        include_prompt_detail=False,
    )
    return AgentManager(lambda: config), toml_path


def test_resolve_edit_path_returns_existing_toml_for_custom_agent(
    manager_with_custom_agent: tuple[AgentManager, Path],
) -> None:
    manager, toml_path = manager_with_custom_agent
    result = resolve_edit_path("my-custom", manager)
    assert result == toml_path


def test_resolve_edit_path_creates_override_for_builtin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VIBE_HOME", str(tmp_path / "vibe_home"))

    config = build_test_vibe_config(
        include_project_context=False, include_prompt_detail=False
    )
    manager = AgentManager(lambda: config)

    result = resolve_edit_path("default", manager)

    assert result.exists()
    assert result.suffix == ".toml"
    assert result.parent == tmp_path / "vibe_home" / "agents"
    content = result.read_text()
    assert "description" in content
    assert "safety" in content
    assert "default" in content


def test_resolve_edit_path_returns_existing_override_on_second_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VIBE_HOME", str(tmp_path / "vibe_home"))

    config = build_test_vibe_config(
        include_project_context=False, include_prompt_detail=False
    )
    manager = AgentManager(lambda: config)

    first = resolve_edit_path("default", manager)
    first.write_text("description = 'Hand-edited'\nsafety = 'neutral'\n")
    # reload_from_disk() is required so the agents dir (just created by the
    # first resolve_edit_path call) is picked up by _compute_search_paths;
    # without it, _find_on_disk_toml returns None and the second call would
    # overwrite the hand-edited content.
    manager.reload_from_disk()
    second = resolve_edit_path("default", manager)

    assert first == second
    assert "Hand-edited" in second.read_text()


def test_resolve_edit_path_raises_for_unknown_agent(tmp_path: Path) -> None:
    config = build_test_vibe_config(
        agent_paths=[tmp_path / "agents"],
        include_project_context=False,
        include_prompt_detail=False,
    )
    (tmp_path / "agents").mkdir()
    manager = AgentManager(lambda: config)

    with pytest.raises(AgentEditorError):
        resolve_edit_path("does-not-exist", manager)


def test_resolve_edit_path_raises_when_builtin_filtered_by_config(
    tmp_path: Path,
) -> None:
    config = build_test_vibe_config(
        agent_paths=[tmp_path / "agents"],
        enabled_agents=["plan"],
        include_project_context=False,
        include_prompt_detail=False,
    )
    (tmp_path / "agents").mkdir()
    manager = AgentManager(lambda: config, initial_agent="plan")

    assert "default" in BUILTIN_AGENTS
    assert "default" not in manager.available_agents

    with pytest.raises(AgentEditorError):
        resolve_edit_path("default", manager)

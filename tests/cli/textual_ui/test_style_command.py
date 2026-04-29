from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.conftest import (
    build_test_agent_loop,
    build_test_vibe_app,
    build_test_vibe_config,
)


def _widget_content(widget: Any) -> str:
    """Extract the text content from a UserCommandMessage or ErrorMessage widget."""
    if hasattr(widget, "_content"):
        return widget._content
    if hasattr(widget, "_error"):
        return widget._error
    return str(widget)


class TestStyleHandlerListing:
    @pytest.mark.asyncio
    async def test_bare_style_lists_builtin_styles(self) -> None:
        app = build_test_vibe_app()
        captured: list[Any] = []

        async def _capture(widget: Any) -> None:
            captured.append(widget)

        app._mount_and_scroll = _capture  # type: ignore[method-assign]

        await app._set_output_style(cmd_args="")

        rendered = "\n".join(_widget_content(w) for w in captured)
        assert "default" in rendered
        assert "concise" in rendered
        assert "learner" in rendered

    @pytest.mark.asyncio
    async def test_listing_marks_active_style(self) -> None:
        config = build_test_vibe_config(output_style="concise")
        loop = build_test_agent_loop(config=config)
        app = build_test_vibe_app(agent_loop=loop)
        captured: list[Any] = []

        async def _capture(widget: Any) -> None:
            captured.append(widget)

        app._mount_and_scroll = _capture  # type: ignore[method-assign]

        await app._set_output_style(cmd_args="")

        rendered = "\n".join(_widget_content(w) for w in captured)
        # Tighter than just `"*(active)*" in rendered`: assert the marker
        # lives on the same line as the active style name, and on no other.
        active_lines = [line for line in rendered.splitlines() if "*(active)*" in line]
        assert len(active_lines) == 1, (
            f"Expected exactly one *(active)* line, got {active_lines!r}"
        )
        assert "`concise`" in active_lines[0]
        assert "`default`" not in active_lines[0]
        assert "`learner`" not in active_lines[0]

    @pytest.mark.asyncio
    async def test_listing_includes_user_styles(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A user-dropped style under ~/.vibe/prompts/styles/ must appear in
        the /style listing with the *(user)* marker.
        """
        user_dir = tmp_path / "user_styles"
        user_dir.mkdir()
        (user_dir / "myteam.md").write_text(
            "# Myteam style\nbe pithy", encoding="utf-8"
        )

        from vibe.core.output_styles import StyleManager as _StyleManager

        original_init = _StyleManager.__init__

        def _patched_init(
            self: _StyleManager,
            builtin_dir: Path | None = None,
            user_dir_arg: Path | None = None,
        ) -> None:
            original_init(self, builtin_dir=builtin_dir, user_dir=user_dir)

        monkeypatch.setattr(_StyleManager, "__init__", _patched_init)

        app = build_test_vibe_app()
        captured: list[Any] = []

        async def _capture(widget: Any) -> None:
            captured.append(widget)

        app._mount_and_scroll = _capture  # type: ignore[method-assign]

        await app._set_output_style(cmd_args="")

        rendered = "\n".join(_widget_content(w) for w in captured)
        myteam_lines = [line for line in rendered.splitlines() if "`myteam`" in line]
        assert len(myteam_lines) == 1, rendered
        assert "*(user)*" in myteam_lines[0]


class TestStyleHandlerSwitch:
    @pytest.mark.asyncio
    async def test_valid_style_updates_system_prompt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from vibe.core.config import VibeConfig

        monkeypatch.setattr(
            VibeConfig, "save_updates", classmethod(lambda cls, u: None)
        )

        config = build_test_vibe_config(output_style="default")
        loop = build_test_agent_loop(config=config)
        app = build_test_vibe_app(agent_loop=loop)
        captured: list[Any] = []

        async def _capture(widget: Any) -> None:
            captured.append(widget)

        app._mount_and_scroll = _capture  # type: ignore[method-assign]

        def _fake_refresh() -> None:
            new_cfg = loop._base_config.model_copy(update={"output_style": "concise"})
            loop._base_config = new_cfg
            loop.agent_manager.invalidate_config()

        loop.refresh_config = _fake_refresh  # type: ignore[method-assign]

        await app._set_output_style(cmd_args="concise")

        new_system = loop.messages[0].content or ""
        assert "Output Style: Concise" in new_system
        assert loop.config.output_style == "concise"

    @pytest.mark.asyncio
    async def test_unknown_style_shows_error_without_mutating(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from vibe.core.config import VibeConfig

        save_calls: list[dict] = []
        monkeypatch.setattr(
            VibeConfig, "save_updates", classmethod(lambda cls, u: save_calls.append(u))
        )

        config = build_test_vibe_config(output_style="default")
        loop = build_test_agent_loop(config=config)
        app = build_test_vibe_app(agent_loop=loop)
        captured: list[Any] = []

        async def _capture(widget: Any) -> None:
            captured.append(widget)

        app._mount_and_scroll = _capture  # type: ignore[method-assign]

        await app._set_output_style(cmd_args="does-not-exist")

        assert not save_calls
        rendered = "\n".join(_widget_content(w) for w in captured)
        assert "does-not-exist" in rendered or "Unknown" in rendered
        assert loop.config.output_style == "default"


class TestStyleSwitchInPlanMode:
    """/style switching while in PLAN profile must not disturb plan-mode state.

    The handler now goes through agent_loop.refresh_system_prompt(), which is
    profile-aware. This test pins that switching style while the profile is
    PLAN: (a) actually rewrites messages[0] with the new preamble, and
    (b) does NOT side-effect the profile (a future refactor that accidentally
    swaps profile during refresh would be caught here).
    """

    @pytest.mark.asyncio
    async def test_concise_switch_keeps_plan_profile(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from vibe.core.agents.models import BuiltinAgentName
        from vibe.core.config import VibeConfig

        monkeypatch.setattr(
            VibeConfig, "save_updates", classmethod(lambda cls, u: None)
        )

        config = build_test_vibe_config(output_style="default")
        loop = build_test_agent_loop(
            config=config, agent_name=BuiltinAgentName.PLAN
        )
        app = build_test_vibe_app(agent_loop=loop)
        captured: list[Any] = []

        async def _capture(widget: Any) -> None:
            captured.append(widget)

        app._mount_and_scroll = _capture  # type: ignore[method-assign]

        # Mirror the production refresh_config behavior the way the existing
        # TestStyleHandlerSwitch suite does: simulate the config reload that
        # would normally pick up the just-written file.
        def _fake_refresh() -> None:
            new_cfg = loop._base_config.model_copy(update={"output_style": "concise"})
            loop._base_config = new_cfg
            loop.agent_manager.invalidate_config()

        loop.refresh_config = _fake_refresh  # type: ignore[method-assign]

        # Sanity: started in PLAN.
        assert loop.agent_profile.name == BuiltinAgentName.PLAN

        await app._set_output_style(cmd_args="concise")

        # Style took effect: concise preamble landed in messages[0].
        assert "Output Style: Concise" in (loop.messages[0].content or "")
        # Profile must still be PLAN — the prompt rebuild is profile-aware,
        # but it is NOT a profile switch.
        assert loop.agent_profile.name == BuiltinAgentName.PLAN
        # Confirm message at index 0 is the (refreshed) system prompt.
        from vibe.core.types import Role
        assert loop.messages[0].role == Role.system

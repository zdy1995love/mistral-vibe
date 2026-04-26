from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import build_test_agent_loop, build_test_vibe_app, build_test_vibe_config


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
        assert "concise" in rendered
        assert "*(active)*" in rendered


class TestStyleHandlerSwitch:
    @pytest.mark.asyncio
    async def test_valid_style_updates_system_prompt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from vibe.core.config import VibeConfig

        monkeypatch.setattr(VibeConfig, "save_updates", classmethod(lambda cls, u: None))

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

        new_system = loop.messages[0].content
        assert "Output Style: Concise" in new_system
        assert loop.config.output_style == "concise"

    @pytest.mark.asyncio
    async def test_unknown_style_shows_error_without_mutating(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from vibe.core.config import VibeConfig

        save_calls: list[dict] = []
        monkeypatch.setattr(
            VibeConfig,
            "save_updates",
            classmethod(lambda cls, u: save_calls.append(u)),
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

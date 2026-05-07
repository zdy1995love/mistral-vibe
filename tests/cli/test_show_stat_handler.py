from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from vibe.cli.textual_ui.app import VibeApp
from vibe.core.types import AgentStats


@pytest.fixture
def app_stub() -> VibeApp:
    """Construct a VibeApp stub with the minimum surface _show_stat touches."""
    app = VibeApp.__new__(VibeApp)
    app.agent_loop = MagicMock()
    app.agent_loop.stats = AgentStats()
    app.agent_loop.config = MagicMock()
    active_model = MagicMock()
    active_model.auto_compact_threshold = 131072
    app.agent_loop.config.get_active_model.return_value = active_model
    app._mount_and_scroll = AsyncMock()
    app._switch_to_stat_timeline_app = AsyncMock()
    return app


@pytest.mark.asyncio
async def test_show_stat_no_arg_mounts_overview(app_stub: VibeApp) -> None:
    await app_stub._show_stat(cmd_args="")
    assert app_stub._mount_and_scroll.await_count == 1
    arg = app_stub._mount_and_scroll.await_args.args[0]
    from vibe.cli.textual_ui.widgets.stat_overview import StatOverviewMessage
    assert isinstance(arg, StatOverviewMessage)


@pytest.mark.asyncio
async def test_show_stat_timeline_arg_switches_app(app_stub: VibeApp) -> None:
    await app_stub._show_stat(cmd_args="timeline")
    assert app_stub._switch_to_stat_timeline_app.await_count == 1
    assert app_stub._mount_and_scroll.await_count == 0


@pytest.mark.asyncio
async def test_show_stat_unknown_arg_mounts_error(app_stub: VibeApp) -> None:
    await app_stub._show_stat(cmd_args="bogus")
    assert app_stub._mount_and_scroll.await_count == 1
    from vibe.cli.textual_ui.widgets.messages import ErrorMessage
    arg = app_stub._mount_and_scroll.await_args.args[0]
    assert isinstance(arg, ErrorMessage)

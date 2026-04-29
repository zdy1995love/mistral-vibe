from __future__ import annotations

from textual.pilot import Pilot

from tests.conftest import build_test_vibe_config
from tests.snapshots.base_snapshot_test_app import BaseSnapshotTestApp
from tests.snapshots.snap_compare import SnapCompare


def _agents_picker_config():
    return build_test_vibe_config(
        active_model="devstral",
        disable_welcome_banner_animation=True,
        displayed_workdir="/test/workdir",
        include_project_context=False,
        include_prompt_detail=False,
    )


class AgentsPickerTestApp(BaseSnapshotTestApp):
    def __init__(self):
        super().__init__(config=_agents_picker_config())

    async def on_mount(self) -> None:
        await super().on_mount()
        await self._switch_to_agents_picker_app()


def test_snapshot_agents_picker_initial(snap_compare: SnapCompare) -> None:
    async def run_before(pilot: Pilot) -> None:
        await pilot.pause(0.2)

    assert snap_compare(
        "test_ui_snapshot_agents_picker.py:AgentsPickerTestApp",
        terminal_size=(100, 36),
        run_before=run_before,
    )


def test_snapshot_agents_picker_navigate_down(snap_compare: SnapCompare) -> None:
    async def run_before(pilot: Pilot) -> None:
        await pilot.pause(0.2)
        await pilot.press("down")
        await pilot.pause(0.1)

    assert snap_compare(
        "test_ui_snapshot_agents_picker.py:AgentsPickerTestApp",
        terminal_size=(100, 36),
        run_before=run_before,
    )


def test_snapshot_agents_picker_escape_cancels(snap_compare: SnapCompare) -> None:
    async def run_before(pilot: Pilot) -> None:
        await pilot.pause(0.2)
        await pilot.press("escape")
        await pilot.pause(0.2)

    assert snap_compare(
        "test_ui_snapshot_agents_picker.py:AgentsPickerTestApp",
        terminal_size=(100, 36),
        run_before=run_before,
    )

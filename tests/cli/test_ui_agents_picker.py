from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import build_test_vibe_app, build_test_vibe_config


def _config_with_user_agents_dir(tmp_path: Path):
    (tmp_path / "vibe_home").mkdir()
    return build_test_vibe_config(
        agent_paths=[tmp_path / "agents"],
        disable_welcome_banner_animation=True,
        displayed_workdir=str(tmp_path),
    )


class _NullCM:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.mark.asyncio
async def test_edit_flow_invokes_editor_and_reloads_manager(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VIBE_HOME", str(tmp_path / "vibe_home"))

    config = _config_with_user_agents_dir(tmp_path)
    app = build_test_vibe_app(config=config)

    fake_run = MagicMock(return_value=MagicMock(returncode=0))
    # HeadlessDriver.can_suspend is a read-only property that returns False.
    # Patch it on the class so the suspend branch is taken.
    from textual.drivers.headless_driver import HeadlessDriver

    with (
        patch("subprocess.run", fake_run),
        patch.object(app, "suspend", lambda: _NullCM()),
        patch.object(
            HeadlessDriver,
            "can_suspend",
            new_callable=lambda: property(lambda self: True),
        ),
    ):
        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            await app._switch_to_agents_picker_app()
            await pilot.pause(0.2)
            await pilot.press("enter")
            await pilot.pause(0.2)

    fake_run.assert_called_once()

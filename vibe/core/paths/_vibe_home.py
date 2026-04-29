from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path

from vibe import VIBE_ROOT


class GlobalPath:
    def __init__(self, resolver: Callable[[], Path]) -> None:
        self._resolver = resolver

    @property
    def path(self) -> Path:
        return self._resolver()


_DEFAULT_VIBE_HOME = Path.home() / ".vibe"


def _get_vibe_home() -> Path:
    if vibe_home := os.getenv("VIBE_HOME"):
        return Path(vibe_home).expanduser().resolve()
    return _DEFAULT_VIBE_HOME


VIBE_HOME = GlobalPath(_get_vibe_home)
GLOBAL_ENV_FILE = GlobalPath(lambda: VIBE_HOME.path / ".env")
SESSION_LOG_DIR = GlobalPath(lambda: VIBE_HOME.path / "logs" / "session")
TRUSTED_FOLDERS_FILE = GlobalPath(lambda: VIBE_HOME.path / "trusted_folders.toml")
LOG_DIR = GlobalPath(lambda: VIBE_HOME.path / "logs")
LOG_FILE = GlobalPath(lambda: VIBE_HOME.path / "logs" / "vibe.log")
HISTORY_FILE = GlobalPath(lambda: VIBE_HOME.path / "vibehistory")
# PLANS_DIR is project-local, not under VIBE_HOME — plans co-locate with the
# code they describe so multiple projects don't collide and a plan stays with
# its repo. Resolved from cwd at access time; stable for the duration of a
# session because vibe-cli doesn't chdir.
PLANS_DIR = GlobalPath(lambda: Path.cwd() / ".vibe" / "plans")

DEFAULT_TOOL_DIR = GlobalPath(lambda: VIBE_ROOT / "core" / "tools" / "builtins")

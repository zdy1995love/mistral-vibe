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
CACHE_FILE = GlobalPath(lambda: VIBE_HOME.path / "cache.toml")
HISTORY_FILE = GlobalPath(lambda: VIBE_HOME.path / "vibehistory")
# PLANS_DIR lives under VIBE_HOME (not cwd). Earlier the design was
# cwd-relative — "plans co-locate with the code they describe" — but
# `_plan_overrides()` runs at module import time (capturing cwd before
# any cli chdir) while `PlanSession.plan_file_path` lazy-initialises at
# first reminder injection. In some sessions those two cwds drifted,
# producing a stale `ctx.plan_file_path` in `exit_plan_mode` even though
# the file existed on disk. Plans are a transient artifact (consumed
# once on fork-to-dev), so the loss of project co-location is acceptable
# in exchange for cwd-independence and uniformity with sessions/ + logs/.
PLANS_DIR = GlobalPath(lambda: VIBE_HOME.path / "plans")

DEFAULT_TOOL_DIR = GlobalPath(lambda: VIBE_ROOT / "core" / "tools" / "builtins")

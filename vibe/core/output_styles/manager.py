from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from vibe import VIBE_ROOT
from vibe.core.paths import VIBE_HOME

_BUILTIN_STYLES_DIR = VIBE_ROOT / "core" / "prompts" / "styles"


class StyleNotFoundError(LookupError):
    """Raised when load() is called with an unknown style name."""


@dataclass(frozen=True)
class StyleInfo:
    name: str
    source: str  # "builtin" | "user"
    path: Path
    is_active: bool = False


class StyleManager:
    """Discover + load output-style markdown files.

    Built-in styles live under ``vibe/core/prompts/styles/*.md``.
    User overrides live under ``$VIBE_HOME/prompts/styles/*.md`` and win
    on name collision. Style names are filename stems (case-sensitive).
    """

    def __init__(
        self,
        builtin_dir: Path | None = None,
        user_dir: Path | None = None,
    ) -> None:
        self._builtin_dir = builtin_dir or _BUILTIN_STYLES_DIR
        self._user_dir_override = user_dir

    def _resolved_user_dir(self) -> Path:
        if self._user_dir_override is not None:
            return self._user_dir_override
        return VIBE_HOME.path / "prompts" / "styles"

    def _scan(self, directory: Path) -> dict[str, Path]:
        if not directory.is_dir():
            return {}
        return {
            entry.stem: entry
            for entry in directory.iterdir()
            if entry.is_file() and entry.suffix == ".md"
        }

    def _merged(self) -> dict[str, StyleInfo]:
        """Return name -> StyleInfo with user dir winning over builtin."""
        merged: dict[str, StyleInfo] = {}
        for name, path in self._scan(self._builtin_dir).items():
            merged[name] = StyleInfo(name=name, source="builtin", path=path)
        for name, path in self._scan(self._resolved_user_dir()).items():
            merged[name] = StyleInfo(name=name, source="user", path=path)
        return merged

    def list_styles(self) -> list[str]:
        """Return sorted, deduped list of style names."""
        return sorted(self._merged().keys())

    def list_styles_with_metadata(self, active: str | None = None) -> list[StyleInfo]:
        """Return sorted StyleInfo list, marking the active style if any."""
        merged = self._merged()
        return [
            StyleInfo(
                name=info.name,
                source=info.source,
                path=info.path,
                is_active=(active == info.name),
            )
            for info in (merged[k] for k in sorted(merged))
        ]

    def load(self, name: str) -> str:
        """Read and return the (stripped) text of the named style."""
        info = self._merged().get(name)
        if info is None:
            raise StyleNotFoundError(name)
        return info.path.read_text(encoding="utf-8").strip()

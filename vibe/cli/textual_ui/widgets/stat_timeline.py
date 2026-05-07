from __future__ import annotations

from collections import Counter
from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container, Vertical
from textual.message import Message
from textual.widgets import DataTable, Label, Static

from vibe.core.types import AgentStats, TurnRecord


def format_tools_cell(tools: list[str], max_width: int = 30) -> str:
    if not tools:
        return "─"
    counts: Counter[str] = Counter(tools)
    parts: list[str] = []
    for name, n in counts.items():
        parts.append(f"{name}×{n}" if n > 1 else name)
    out = ", ".join(parts)
    if len(out) > max_width:
        out = out[: max_width - 1].rstrip(", ") + "…"
    return out


def cache_sparkline(pct: int) -> str:
    cells = max(0, min(4, round(pct / 25)))
    return "▓" * cells + "░" * (4 - cells)


def _cache_pct(cached: int, prompt: int) -> int:
    if prompt <= 0:
        return 0
    return round(100 * cached / prompt)


_FULL_COLUMNS = ("#", "Input", "Cached", "sparkline", "Cache%", "Output", "Duration", "tools")
_MEDIUM_COLUMNS = ("#", "Input", "Cached", "Cache%", "Output", "Duration", "tools")
_NARROW_COLUMNS = ("#", "Input", "Cached", "Cache%", "Output", "Duration")


def timeline_columns_for_width(width: int) -> tuple[str, ...]:
    if width >= 90:
        return _FULL_COLUMNS
    if width >= 70:
        return _MEDIUM_COLUMNS
    return _NARROW_COLUMNS


def _row_for(rec: TurnRecord, columns: tuple[str, ...]) -> tuple[str, ...]:
    pct = _cache_pct(rec.cached_tokens, rec.prompt_tokens)
    cells: list[str] = []
    for col in columns:
        if col == "#":
            cells.append(str(rec.index))
        elif col == "Input":
            cells.append(f"{rec.prompt_tokens:,}")
        elif col == "Cached":
            cells.append(f"{rec.cached_tokens:,}")
        elif col == "sparkline":
            cells.append(cache_sparkline(pct))
        elif col == "Cache%":
            cells.append(f"{pct}%" if rec.prompt_tokens > 0 else "—")
        elif col == "Output":
            cells.append(f"{rec.completion_tokens:,}")
        elif col == "Duration":
            cells.append(f"{rec.duration:.1f}s")
        elif col == "tools":
            cells.append(format_tools_cell(rec.tools))
        else:
            raise ValueError(f"_row_for: unknown column {col!r}")
    return tuple(cells)


class StatTimelineApp(Container):
    """Stat timeline bottom app for /stat."""

    can_focus_children = True

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "close", "Close", show=False),
        Binding("g", "scroll_top", "Top"),
        Binding("G", "scroll_bottom", "Bottom"),
    ]

    class Cancelled(Message):
        pass

    def __init__(self, stats: AgentStats, **kwargs: Any) -> None:
        super().__init__(id="stat-timeline-app", **kwargs)
        self._stats = stats

    def action_close(self) -> None:
        self.post_message(self.Cancelled())

    def compose(self) -> ComposeResult:
        with Vertical(id="stat-timeline-root"):
            total_p = self._stats.session_prompt_tokens
            total_c = self._stats.session_cached_tokens
            pct = _cache_pct(total_c, total_p)
            yield Label(
                f"Per-turn timeline · {len(self._stats.turns)} turns · {pct}% cache hit",
                id="stat-timeline-header",
            )
            if not self._stats.turns:
                yield Static(
                    "No turns yet — this becomes more useful after a few exchanges.",
                    id="stat-timeline-empty",
                )
                return
            yield DataTable(id="stat-timeline-table")

    def on_mount(self) -> None:
        if not self._stats.turns:
            return
        table = self.query_one(DataTable)
        width = self.size.width or 100
        columns = timeline_columns_for_width(width)
        for col in columns:
            table.add_column(col)
        for rec in self._stats.turns:
            table.add_row(*_row_for(rec, columns))

    def action_scroll_top(self) -> None:
        try:
            t = self.query_one(DataTable)
        except Exception:
            return
        t.move_cursor(row=0)

    def action_scroll_bottom(self) -> None:
        try:
            t = self.query_one(DataTable)
        except Exception:
            return
        t.move_cursor(row=max(0, t.row_count - 1))

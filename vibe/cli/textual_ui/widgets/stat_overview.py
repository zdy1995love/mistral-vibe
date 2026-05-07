from __future__ import annotations

from typing import Any

from rich import box
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from vibe.cli.textual_ui.widgets.messages import ExpandingBorder
from vibe.core.types import AgentStats


def _fmt_int(n: int) -> str:
    return f"{n:,}"


def _fmt_cost(c: float) -> str:
    if c < 1:
        return f"${c:,.4f}"
    return f"${c:,.2f}"


def _cache_pct(cached: int, prompt: int) -> int | None:
    if prompt <= 0:
        return None
    return round(100 * cached / prompt)


def _cache_color(pct: int) -> str:
    if pct >= 80:
        return "green"
    if pct >= 50:
        return "yellow"
    return "dim"


def _context_bar(current: int, max_tokens: int, width: int = 24) -> Text:
    if max_tokens <= 0:
        return Text(f"{_fmt_int(current)} tokens")
    ratio = min(1.0, current / max_tokens)
    filled = round(ratio * width)
    if ratio < 0.5:
        color = "green"
    elif ratio < 0.8:
        color = "yellow"
    else:
        color = "red"
    bar = Text()
    bar.append("█" * filled, style=color)
    bar.append("░" * (width - filled), style="dim")
    bar.append(f"  {_fmt_int(current)} / {_fmt_int(max_tokens)}  ({ratio:.0%})")
    return bar


def render_stat_overview(stats: AgentStats, max_context: int) -> RenderableType:
    """Render the inline /stat overview as a Rich Panel."""
    if not stats.turns:
        return Panel(
            Text("No turns yet — send a message to start.", style="dim"),
            title="Stat",
            box=box.SQUARE,
            border_style="dim",
            padding=(1, 2),
        )

    session_col = Table.grid(padding=(0, 1))
    session_col.add_column(style="bold", min_width=7)
    session_col.add_column(justify="right", min_width=7)
    session_col.add_column()  # cache% suffix

    session_col.add_row(Text("Session", style="bold"), "", "")
    session_col.add_row("───────", "", "")
    session_col.add_row("Turns", _fmt_int(stats.steps), "")
    session_col.add_row("Input", _fmt_int(stats.session_prompt_tokens), "")

    pct = _cache_pct(stats.session_cached_tokens, stats.session_prompt_tokens)
    cache_suffix: Any = ""
    if pct is not None:
        cache_suffix = Text(f"{pct}%", style=_cache_color(pct))
    session_col.add_row("Cached", _fmt_int(stats.session_cached_tokens), cache_suffix)
    session_col.add_row("Output", _fmt_int(stats.session_completion_tokens), "")

    session_col.add_row("Cost", _fmt_cost(stats.session_cost), "")

    last_col = Table.grid(padding=(0, 1))
    last_col.add_column(style="bold", min_width=9)
    last_col.add_column(justify="right", min_width=7)
    last_col.add_column()
    last_col.add_row(Text("Last turn", style="bold"), "", "")
    last_col.add_row("─────────", "", "")
    last_col.add_row("Input", _fmt_int(stats.last_turn_prompt_tokens), "")

    last_pct = _cache_pct(stats.last_turn_cached_tokens, stats.last_turn_prompt_tokens)
    last_suffix: Any = ""
    if last_pct is not None:
        last_suffix = Text(f"{last_pct}%", style=_cache_color(last_pct))
    last_col.add_row("Cached", _fmt_int(stats.last_turn_cached_tokens), last_suffix)
    last_col.add_row("Output", _fmt_int(stats.last_turn_completion_tokens), "")

    columns = Table.grid(padding=(0, 4))
    columns.add_column()
    columns.add_column()
    columns.add_row(session_col, last_col)

    context_line = Text("Context  ")
    context_line.append_text(_context_bar(stats.context_tokens, max_context))

    body = Group(columns, Text(""), context_line)
    return Panel(
        body,
        title="Stat",
        box=box.SQUARE,
        border_style="bright_black",
        padding=(1, 2),
    )


class StatOverviewMessage(Static):
    """Inline /stat overview message. Pure read-only; no key bindings."""

    def __init__(self, stats: AgentStats, max_context: int, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.add_class("stat-overview-message")
        self._stats = stats
        self._max_context = max_context

    def compose(self) -> ComposeResult:
        with Horizontal(classes="stat-overview-container"):
            yield ExpandingBorder(classes="stat-overview-border")
            with Vertical(classes="stat-overview-content"):
                yield Static(render_stat_overview(self._stats, self._max_context))

from __future__ import annotations

from rich.console import Console

from vibe.cli.textual_ui.widgets.stat_overview import render_stat_overview
from vibe.core.types import AgentStats, TurnRecord


def _render(stats: AgentStats, max_context: int = 0) -> str:
    console = Console(width=80, color_system=None, record=True)
    console.print(render_stat_overview(stats=stats, max_context=max_context))
    return console.export_text()


def test_overview_empty_session_renders_hint() -> None:
    out = _render(AgentStats())
    assert "No turns yet" in out


def test_overview_renders_session_and_last_turn_columns() -> None:
    stats = AgentStats(
        steps=12,
        session_prompt_tokens=18432,
        session_cached_tokens=16210,
        session_completion_tokens=1204,
        last_turn_prompt_tokens=1024,
        last_turn_cached_tokens=1016,
        last_turn_completion_tokens=42,
        context_tokens=52408,
        input_price_per_million=1.5,
        output_price_per_million=7.5,
    )
    stats.turns.append(
        TurnRecord(
            index=12,
            prompt_tokens=1024,
            cached_tokens=1016,
            completion_tokens=42,
            duration=1.8,
            started_at=0.0,
        )
    )
    out = _render(stats, max_context=131072)
    assert "Session" in out
    assert "Last turn" in out
    assert "12" in out  # turns
    assert "18,432" in out  # session input
    assert "16,210" in out  # session cached
    assert "1,204" in out  # session output
    assert "Cost" in out
    # cost = 18432/1M * 1.5 + 1204/1M * 7.5 = 0.027648 + 0.00903 = 0.036678
    assert "$0.0367" in out or "$0.0366" in out
    # context bar
    assert "52,408" in out and "131,072" in out
    # cache pct: 16210/18432 = 87.9% -> 88%
    assert "88%" in out


def test_fmt_cost_branches() -> None:
    from vibe.cli.textual_ui.widgets.stat_overview import _fmt_cost

    assert _fmt_cost(0.0037) == "$0.0037"
    assert _fmt_cost(1.5) == "$1.50"
    assert _fmt_cost(123.456) == "$123.46"


def test_overview_no_max_context_skips_bar() -> None:
    stats = AgentStats(
        steps=1,
        context_tokens=500,
        session_prompt_tokens=500,
        session_completion_tokens=10,
    )
    stats.turns.append(
        TurnRecord(
            index=1,
            prompt_tokens=500,
            cached_tokens=0,
            completion_tokens=10,
            duration=0.5,
            started_at=0.0,
        )
    )
    out = _render(stats, max_context=0)
    assert "500" in out
    assert (
        "/" not in out.split("Context")[1].split("\n")[0]
    )  # no denominator on context line

from __future__ import annotations

from vibe.cli.textual_ui.widgets.stat_timeline import (
    format_tools_cell,
    cache_sparkline,
    timeline_columns_for_width,
)
from vibe.core.types import TurnRecord


def test_format_tools_cell_dedup_with_count() -> None:
    assert format_tools_cell([]) == "─"
    assert format_tools_cell(["read"]) == "read"
    assert format_tools_cell(["read", "read"]) == "read×2"
    assert format_tools_cell(["edit", "edit", "bash"]) == "edit×2, bash"


def test_format_tools_cell_truncates_at_width() -> None:
    out = format_tools_cell(["read", "bash", "edit", "grep", "find"], max_width=12)
    assert len(out) <= 12
    assert out.endswith("…")


def test_cache_sparkline_quantizes_to_4_cells() -> None:
    assert cache_sparkline(0) == "░░░░"
    assert cache_sparkline(12) == "░░░░"   # round(12/25)=0
    assert cache_sparkline(40) == "▓▓░░"   # round(40/25)=2
    assert cache_sparkline(78) == "▓▓▓░"   # round(78/25)=3
    assert cache_sparkline(95) == "▓▓▓▓"
    assert cache_sparkline(120) == "▓▓▓▓"  # clamp


def test_timeline_columns_for_width_drops_columns_under_thresholds() -> None:
    full = timeline_columns_for_width(100)
    assert "tools" in full and "sparkline" in full
    medium = timeline_columns_for_width(80)
    assert "tools" in medium
    assert "sparkline" not in medium
    narrow = timeline_columns_for_width(65)
    assert "tools" not in narrow
    assert "sparkline" not in narrow


def test_row_for_raises_on_unknown_column() -> None:
    import pytest
    from vibe.cli.textual_ui.widgets.stat_timeline import _row_for

    rec = TurnRecord(
        index=1, prompt_tokens=100, cached_tokens=50,
        completion_tokens=20, duration=0.5, started_at=0.0,
    )
    with pytest.raises(ValueError, match="unknown column"):
        _row_for(rec, ("#", "Input", "BogusColumn"))

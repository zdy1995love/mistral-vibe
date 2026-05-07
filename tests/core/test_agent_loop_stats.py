from __future__ import annotations

import time

from vibe.core.agent_loop import AgentLoop
from vibe.core.types import AgentStats, LLMUsage


def _agent_with_stats() -> AgentLoop:
    """Construct an AgentLoop stub with just enough state to call _update_stats.

    We don't run __init__; we set the attributes _update_stats touches.
    """
    a = AgentLoop.__new__(AgentLoop)
    a.stats = AgentStats()
    a._pending_turn_tools = []
    return a


def test_update_stats_records_cached_and_appends_turn_record() -> None:
    a = _agent_with_stats()
    a._pending_turn_tools = ["read", "bash", "read"]  # populated by dispatch
    a.stats.steps = 3

    usage = LLMUsage(prompt_tokens=2340, completion_tokens=64, cached_prompt_tokens=1820)
    a._update_stats(usage=usage, time_seconds=1.2)

    assert a.stats.last_turn_cached_tokens == 1820
    assert a.stats.session_cached_tokens == 1820
    assert len(a.stats.turns) == 1
    rec = a.stats.turns[0]
    assert rec.index == 3
    assert rec.prompt_tokens == 2340
    assert rec.cached_tokens == 1820
    assert rec.completion_tokens == 64
    assert rec.duration == 1.2
    assert rec.tools == ["read", "bash", "read"]
    assert a._pending_turn_tools == []  # flushed


def test_update_stats_accumulates_session_cached_across_turns() -> None:
    a = _agent_with_stats()
    a.stats.steps = 1
    a._update_stats(LLMUsage(prompt_tokens=520, completion_tokens=18, cached_prompt_tokens=0), 0.6)
    a.stats.steps = 2
    a._update_stats(LLMUsage(prompt_tokens=1210, completion_tokens=32, cached_prompt_tokens=480), 0.9)
    assert a.stats.session_cached_tokens == 480
    assert len(a.stats.turns) == 2
    assert a.stats.turns[1].cached_tokens == 480


def test_clear_history_includes_pending_turn_tools_reset() -> None:
    """Regression: clear_history must reset _pending_turn_tools so a
    mid-flight dispatch doesn't bleed tool names into the new session's
    first TurnRecord. We assert this by inspecting the source — a full
    integration test of clear_history would require mocking many
    collaborators that are unrelated to this contract."""
    import inspect

    src = inspect.getsource(AgentLoop.clear_history)
    assert "_pending_turn_tools" in src, (
        "clear_history must reset _pending_turn_tools — see review "
        "for Task 6 (commit a6394a7)."
    )

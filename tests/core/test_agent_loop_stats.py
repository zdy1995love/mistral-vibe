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
    return a


def test_update_stats_records_cached_and_appends_turn_record() -> None:
    a = _agent_with_stats()
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
    assert rec.tools == []  # dispatch hasn't happened yet


def test_update_stats_accumulates_session_cached_across_turns() -> None:
    a = _agent_with_stats()
    a.stats.steps = 1
    a._update_stats(LLMUsage(prompt_tokens=520, completion_tokens=18, cached_prompt_tokens=0), 0.6)
    a.stats.steps = 2
    a._update_stats(LLMUsage(prompt_tokens=1210, completion_tokens=32, cached_prompt_tokens=480), 0.9)
    assert a.stats.session_cached_tokens == 480
    assert len(a.stats.turns) == 2
    assert a.stats.turns[1].cached_tokens == 480


def test_record_dispatched_tool_appends_to_current_turn() -> None:
    a = _agent_with_stats()
    a.stats.steps = 1
    a._update_stats(LLMUsage(prompt_tokens=10, completion_tokens=2), 0.1)
    a._record_dispatched_tool("edit")
    a._record_dispatched_tool("edit")
    assert a.stats.turns[0].tools == ["edit", "edit"]


def test_record_dispatched_tool_before_any_turn_is_safe() -> None:
    """Defensive: if dispatch ever fires before _update_stats has created
    a TurnRecord (shouldn't happen in practice but we don't want to crash),
    the call is a no-op rather than IndexError."""
    a = _agent_with_stats()
    a._record_dispatched_tool("read")  # must not raise
    assert a.stats.turns == []


# --- Real-call-ordering regression tests (0508-issues P0) -----------------
#
# At runtime _update_stats runs FIRST inside _chat / _chat_streaming, then
# _handle_tool_calls dispatches and calls _record_dispatched_tool. So the
# tool name must land on the just-created TurnRecord, not on a future one.
# The earlier `_pending_turn_tools` buffer design had this backwards: the
# flush at the START of _update_stats grabbed the previous turn's pending
# tools, shifting every turn's tool list one slot forward.


def test_tool_dispatched_after_update_stats_lands_on_current_turn() -> None:
    a = _agent_with_stats()
    a.stats.steps = 1
    a._update_stats(LLMUsage(prompt_tokens=100, completion_tokens=10), 0.5)
    a._record_dispatched_tool("read")
    a._record_dispatched_tool("bash")

    assert a.stats.turns[-1].tools == ["read", "bash"]


def test_failed_turn_dispatch_does_not_leak_to_next_turn() -> None:
    a = _agent_with_stats()

    # Turn N: success, dispatches a tool.
    a.stats.steps = 1
    a._update_stats(LLMUsage(prompt_tokens=100, completion_tokens=10), 0.5)
    a._record_dispatched_tool("write")

    # Turn N+1: _chat raises before _update_stats — nothing recorded.

    # Turn N+2: success, no dispatch.
    a.stats.steps = 3
    a._update_stats(LLMUsage(prompt_tokens=120, completion_tokens=5), 0.3)

    assert a.stats.turns[0].tools == ["write"]
    assert a.stats.turns[-1].tools == [], (
        f"failed-turn dispatch leaked into next successful turn: "
        f"{a.stats.turns[-1].tools}"
    )


def test_compaction_turn_does_not_steal_prior_turn_tools() -> None:
    a = _agent_with_stats()

    # User turn 1 with a tool dispatch.
    a.stats.steps = 1
    a._update_stats(LLMUsage(prompt_tokens=100, completion_tokens=10), 0.5)
    a._record_dispatched_tool("read")

    # /compact runs an LLM turn (no dispatch).
    a.stats.steps = 2
    a._update_stats(LLMUsage(prompt_tokens=2000, completion_tokens=500), 1.0)

    assert a.stats.turns[0].tools == ["read"]
    assert a.stats.turns[1].tools == [], (
        f"compaction TurnRecord captured prior turn's tools: "
        f"{a.stats.turns[1].tools}"
    )

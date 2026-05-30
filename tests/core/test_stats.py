from __future__ import annotations

from vibe.core.types import AgentStats, LLMUsage, TurnRecord


def test_llm_usage_cached_default_zero() -> None:
    u = LLMUsage(prompt_tokens=100, completion_tokens=10)
    assert u.cached_prompt_tokens == 0


def test_llm_usage_add_accumulates_cached() -> None:
    a = LLMUsage(prompt_tokens=200, completion_tokens=5, cached_prompt_tokens=180)
    b = LLMUsage(prompt_tokens=300, completion_tokens=8, cached_prompt_tokens=290)
    c = a + b
    assert c.prompt_tokens == 500
    assert c.completion_tokens == 13
    assert c.cached_prompt_tokens == 470


def test_turn_record_fields() -> None:
    t = TurnRecord(
        index=3,
        prompt_tokens=2340,
        cached_tokens=1820,
        completion_tokens=64,
        duration=1.2,
        started_at=1778149052.0,
        tools=["bash"],
    )
    assert t.index == 3
    assert t.tools == ["bash"]


def test_turn_record_tools_list_is_mutable() -> None:
    """tools is mutated by the dispatch layer after the record is appended."""
    t = TurnRecord(
        index=1,
        prompt_tokens=0,
        cached_tokens=0,
        completion_tokens=0,
        duration=0.0,
        started_at=0.0,
    )
    t.tools.append("read")
    assert t.tools == ["read"]


def test_agent_stats_new_fields_default_zero_and_empty() -> None:
    s = AgentStats()
    assert s.session_cached_tokens == 0
    assert s.last_turn_cached_tokens == 0
    assert s.turns == []


def test_agent_stats_round_trip_preserves_turns() -> None:
    s = AgentStats(
        steps=2,
        session_prompt_tokens=1730,
        session_completion_tokens=50,
        session_cached_tokens=480,
    )
    s.turns.append(
        TurnRecord(
            index=1,
            prompt_tokens=520,
            cached_tokens=0,
            completion_tokens=18,
            duration=0.6,
            started_at=0.0,
        )
    )
    s.turns.append(
        TurnRecord(
            index=2,
            prompt_tokens=1210,
            cached_tokens=480,
            completion_tokens=32,
            duration=0.9,
            started_at=1.0,
            tools=["read"],
        )
    )
    dumped = s.model_dump()
    restored = AgentStats.model_validate(dumped)
    assert len(restored.turns) == 2
    assert restored.turns[1].cached_tokens == 480
    assert restored.turns[1].tools == ["read"]
    assert restored.session_cached_tokens == 480


def test_agent_stats_create_fresh_starts_empty_turns() -> None:
    prev = AgentStats(session_prompt_tokens=999)
    prev.turns.append(
        TurnRecord(
            index=1,
            prompt_tokens=999,
            cached_tokens=0,
            completion_tokens=10,
            duration=1.0,
            started_at=0.0,
        )
    )
    fresh = AgentStats.create_fresh(prev)
    assert fresh.session_prompt_tokens == 0
    assert fresh.session_cached_tokens == 0
    assert fresh.turns == []


def test_agent_stats_reset_context_state_clears_last_turn_cached() -> None:
    s = AgentStats(
        last_turn_prompt_tokens=100,
        last_turn_completion_tokens=10,
        last_turn_cached_tokens=80,
        session_prompt_tokens=5000,
        session_cached_tokens=4500,
    )
    s.reset_context_state()
    assert s.last_turn_cached_tokens == 0
    # session totals preserved
    assert s.session_prompt_tokens == 5000
    assert s.session_cached_tokens == 4500

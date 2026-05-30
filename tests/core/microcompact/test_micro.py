from __future__ import annotations

from vibe.core.microcompact import CLEARABLE_TOOLS, micro_compact
from vibe.core.types import AgentStats, LLMMessage, MessageList, Role


def _tool_result(name: str, content: str, call_id: str = "id1") -> LLMMessage:
    return LLMMessage(role=Role.tool, name=name, tool_call_id=call_id, content=content)


def _user(content: str) -> LLMMessage:
    return LLMMessage(role=Role.user, content=content)


def _assistant(content: str) -> LLMMessage:
    return LLMMessage(role=Role.assistant, content=content)


def _make_stats(context_tokens: int) -> AgentStats:
    stats = AgentStats()
    stats.context_tokens = context_tokens
    return stats


class TestMicroCompactBelowThreshold:
    def test_does_nothing_when_below_ratio(self) -> None:
        messages = MessageList([_user("hello"), _tool_result("bash", "x" * 1000, "c1")])
        stats = _make_stats(100)
        # threshold=200_000, ratio=0.7 → micro fires at 140_000; 100 < 140_000
        tokens = micro_compact(
            messages,
            threshold=200_000,
            micro_compact_ratio=0.7,
            micro_keep_last=2,
            stats=stats,
        )
        assert tokens == 0
        assert messages[1].content == "x" * 1000

    def test_returns_zero_when_no_clearable_results(self) -> None:
        messages = MessageList([_user("hello"), _assistant("world")])
        stats = _make_stats(150_000)
        tokens = micro_compact(
            messages,
            threshold=200_000,
            micro_compact_ratio=0.7,
            micro_keep_last=2,
            stats=stats,
        )
        assert tokens == 0


class TestMicroCompactClears:
    def test_clears_old_bash_result(self) -> None:
        big_content = "A" * 4000  # ~1000 tokens
        # Three bash results so default micro_keep_last=2 protects the last two,
        # leaving the oldest (index 1) clearable.
        messages = MessageList([
            _user("run something"),
            _tool_result("bash", big_content, "c1"),  # old, will be cleared
            _tool_result("bash", "recent1", "c2"),  # protected
            _tool_result("bash", "recent2", "c3"),  # protected
            _user("done"),
        ])
        stats = _make_stats(150_000)
        tokens = micro_compact(
            messages,
            threshold=200_000,
            micro_compact_ratio=0.7,
            micro_keep_last=2,
            stats=stats,
        )
        assert tokens > 0
        assert "[Old tool result cleared" in (messages[1].content or "")
        assert "[Old tool result cleared" not in (messages[2].content or "")
        assert "[Old tool result cleared" not in (messages[3].content or "")

    def test_protects_last_n_results_per_tool(self) -> None:
        messages = MessageList([
            _tool_result("bash", "A" * 400, "c1"),  # index 0 — old, should be cleared
            _tool_result("bash", "B" * 400, "c2"),  # index 1 — protected (last 2)
            _tool_result("bash", "C" * 400, "c3"),  # index 2 — protected (last 2)
        ])
        stats = _make_stats(150_000)
        micro_compact(
            messages,
            threshold=200_000,
            micro_compact_ratio=0.7,
            micro_keep_last=2,
            stats=stats,
        )
        assert "[Old tool result cleared" in (messages[0].content or "")
        assert "[Old tool result cleared" not in (messages[1].content or "")
        assert "[Old tool result cleared" not in (messages[2].content or "")

    def test_skips_already_cleared(self) -> None:
        messages = MessageList([
            LLMMessage(
                role=Role.tool,
                name="bash",
                tool_call_id="c1",
                content="[Old tool result cleared — 100 tokens reclaimed]",
            ),
            _tool_result("bash", "fresh" * 100, "c2"),
        ])
        stats = _make_stats(150_000)
        micro_compact(
            messages,
            threshold=200_000,
            micro_compact_ratio=0.7,
            micro_keep_last=2,
            stats=stats,
        )
        assert messages[0].content == "[Old tool result cleared — 100 tokens reclaimed]"

    def test_skips_non_clearable_tools(self) -> None:
        messages = MessageList([
            _tool_result("ask_user_question", "sensitive answer", "c1")
        ])
        stats = _make_stats(150_000)
        tokens = micro_compact(
            messages,
            threshold=200_000,
            micro_compact_ratio=0.7,
            micro_keep_last=2,
            stats=stats,
        )
        assert tokens == 0
        assert messages[0].content == "sensitive answer"

    def test_updates_stats(self) -> None:
        messages = MessageList([
            _tool_result("bash", "A" * 4000, "c1"),  # old, will be cleared
            _tool_result("bash", "recent1", "c2"),  # protected
            _tool_result("bash", "recent2", "c3"),  # protected
        ])
        stats = _make_stats(150_000)
        tokens = micro_compact(
            messages,
            threshold=200_000,
            micro_compact_ratio=0.7,
            micro_keep_last=2,
            stats=stats,
        )
        assert stats.cleared_tool_results == 1
        assert stats.context_tokens < 150_000
        assert tokens > 0

    def test_micro_keep_last_zero_clears_everything_eligible(self) -> None:
        """Edge case: micro_keep_last=0 must NOT protect everything (Python's
        list[-0:] returns the whole list — algorithm must guard against this).
        """
        messages = MessageList([
            _tool_result("bash", "A" * 4000, "c1"),
            _tool_result("bash", "B" * 4000, "c2"),
        ])
        stats = _make_stats(150_000)
        tokens = micro_compact(
            messages,
            threshold=200_000,
            micro_compact_ratio=0.7,
            micro_keep_last=0,
            stats=stats,
        )
        assert tokens > 0
        assert "[Old tool result cleared" in (messages[0].content or "")
        assert "[Old tool result cleared" in (messages[1].content or "")

    def test_greedy_largest_first(self) -> None:
        # Two old messages: small one and large one. Only the large one needed.
        big = "X" * 40_000  # ~10_000 tokens
        small = "y" * 400  # ~100 tokens
        messages = MessageList([
            _tool_result("bash", small, "c1"),  # index 0
            _tool_result("bash", big, "c2"),  # index 1
            _tool_result("bash", "recent", "c3"),  # protected (last 1 if keep_last=1)
        ])
        stats = _make_stats(150_000)
        # keep_last=1, so only index 2 is protected; both 0 and 1 are candidates
        # target savings = 150_000 - (200_000 * 0.5) = 50_000
        # big covers ~10_000, still < 50_000; both will be cleared eventually
        # but big is sorted first
        micro_compact(
            messages,
            threshold=200_000,
            micro_compact_ratio=0.7,
            micro_keep_last=1,
            stats=stats,
        )
        assert "[Old tool result cleared" in (
            messages[1].content or ""
        )  # big was cleared first


class TestClearableToolsList:
    def test_all_expected_tools_present(self) -> None:
        expected = {
            "bash",
            "read_file",
            "write_file",
            "search_replace",
            "grep",
            "web_fetch",
            "web_search",
        }
        assert CLEARABLE_TOOLS == expected


class TestMiddlewareOrdering:
    def test_micro_compact_registered_before_auto_compact(self) -> None:
        """Ordering is load-bearing: MicroCompact mutates context_tokens down so
        AutoCompact re-reads the reduced count and may skip a full compaction.
        """
        from tests.conftest import build_test_agent_loop
        from vibe.core.microcompact import MicroCompactMiddleware
        from vibe.core.middleware import AutoCompactMiddleware

        agent = build_test_agent_loop()
        mws = agent.middleware_pipeline.middlewares
        micro_idx = next(
            i for i, m in enumerate(mws) if isinstance(m, MicroCompactMiddleware)
        )
        auto_idx = next(
            i for i, m in enumerate(mws) if isinstance(m, AutoCompactMiddleware)
        )
        assert micro_idx < auto_idx

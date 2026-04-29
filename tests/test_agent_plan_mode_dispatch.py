from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import build_test_agent_loop, build_test_vibe_config
from tests.mock.utils import mock_llm_chunk
from tests.stubs.fake_backend import FakeBackend
from vibe.core.agents.models import BuiltinAgentName
from vibe.core.types import FunctionCall, Role, ToolCall, ToolResultEvent

PLAN_MODE_ERROR = "[Plan mode: write operations disabled]"


def _write_file_tool_call(path: str, content: str = "hi") -> ToolCall:
    return ToolCall(
        id="call_1",
        index=0,
        function=FunctionCall(
            name="write_file", arguments=json.dumps({"path": path, "content": content})
        ),
    )


def _read_file_tool_call(path: str) -> ToolCall:
    return ToolCall(
        id="call_1",
        index=0,
        function=FunctionCall(name="read_file", arguments=json.dumps({"path": path})),
    )


class TestPlanModeDispatchGate:
    """Integration: agent loop must block write tools when active profile is
    PLAN, and let them through otherwise.
    """

    @pytest.mark.asyncio
    async def test_write_tool_blocked_in_plan_mode(self, tmp_path) -> None:
        target = tmp_path / "f.txt"
        backend = FakeBackend([
            [mock_llm_chunk(tool_calls=[_write_file_tool_call(str(target))])],
            [mock_llm_chunk(content="done")],
        ])
        config = build_test_vibe_config()
        loop = build_test_agent_loop(
            config=config, agent_name=BuiltinAgentName.PLAN, backend=backend
        )

        events = [e async for e in loop.act("write a file please")]
        tool_results = [e for e in events if isinstance(e, ToolResultEvent)]

        assert len(tool_results) == 1
        assert tool_results[0].error is not None
        assert PLAN_MODE_ERROR in tool_results[0].error
        assert not target.exists()

    @pytest.mark.asyncio
    async def test_read_tool_allowed_in_plan_mode(self, tmp_path) -> None:
        target = tmp_path / "f.txt"
        target.write_text("hello")
        backend = FakeBackend([
            [mock_llm_chunk(tool_calls=[_read_file_tool_call(str(target))])],
            [mock_llm_chunk(content="done")],
        ])
        config = build_test_vibe_config()
        loop = build_test_agent_loop(
            config=config, agent_name=BuiltinAgentName.PLAN, backend=backend
        )

        events = [e async for e in loop.act("read the file")]
        tool_results = [e for e in events if isinstance(e, ToolResultEvent)]

        assert len(tool_results) == 1
        assert PLAN_MODE_ERROR not in (tool_results[0].error or "")

    @pytest.mark.asyncio
    async def test_write_tool_runs_normally_outside_plan_mode(self, tmp_path) -> None:
        """Regression: write call blocked in PLAN must succeed under AUTO_APPROVE."""
        target = tmp_path / "f.txt"
        backend = FakeBackend([
            [mock_llm_chunk(tool_calls=[_write_file_tool_call(str(target))])],
            [mock_llm_chunk(content="done")],
        ])
        config = build_test_vibe_config()
        loop = build_test_agent_loop(
            config=config, agent_name=BuiltinAgentName.AUTO_APPROVE, backend=backend
        )

        events = [e async for e in loop.act("write a file")]
        tool_results = [e for e in events if isinstance(e, ToolResultEvent)]

        assert len(tool_results) == 1
        assert PLAN_MODE_ERROR not in (tool_results[0].error or "")
        assert target.exists()
        assert target.read_text() == "hi"

    @pytest.mark.asyncio
    async def test_task_tool_blocked_in_plan_mode(self) -> None:
        """Task is mutates_state=True (subagents may write); gate must fire.

        This pins the contract that even research-style subagent spawning
        is blocked in plan mode — for v1 we play safe. If we later allow
        explicit read-only subagents during planning, this test guards the
        change.
        """
        backend = FakeBackend([
            [
                mock_llm_chunk(
                    tool_calls=[
                        ToolCall(
                            id="call_1",
                            index=0,
                            function=FunctionCall(
                                name="task",
                                arguments=json.dumps(
                                    {"agent": "explore", "task": "find foo"}
                                ),
                            ),
                        )
                    ]
                )
            ],
            [mock_llm_chunk(content="done")],
        ])
        config = build_test_vibe_config()
        loop = build_test_agent_loop(
            config=config, agent_name=BuiltinAgentName.PLAN, backend=backend
        )

        events = [e async for e in loop.act("explore something")]
        tool_results = [e for e in events if isinstance(e, ToolResultEvent)]

        assert len(tool_results) == 1
        assert PLAN_MODE_ERROR in (tool_results[0].error or "")

    @pytest.mark.asyncio
    async def test_error_string_is_wrapped_in_tool_error_tag(self, tmp_path) -> None:
        target = tmp_path / "f.txt"
        backend = FakeBackend([
            [mock_llm_chunk(tool_calls=[_write_file_tool_call(str(target))])],
            [mock_llm_chunk(content="done")],
        ])
        config = build_test_vibe_config()
        loop = build_test_agent_loop(
            config=config, agent_name=BuiltinAgentName.PLAN, backend=backend
        )
        events = [e async for e in loop.act("write")]
        tool_results = [e for e in events if isinstance(e, ToolResultEvent)]
        assert len(tool_results) == 1
        err = tool_results[0].error or ""
        assert "<tool_error>" in err
        assert "</tool_error>" in err
        assert PLAN_MODE_ERROR in err


class TestForkToDev:
    """End-to-end: AgentLoop.fork_to_dev wipes context, switches profile,
    returns a seed string suitable for the next act() call.
    """

    @pytest.mark.asyncio
    async def test_fork_clears_history_switches_and_returns_seed(self) -> None:
        config = build_test_vibe_config()
        loop = build_test_agent_loop(
            config=config, agent_name=BuiltinAgentName.PLAN
        )
        # Simulate plan-mode entry by stashing pre_plan_profile and seeding
        # a planning conversation.
        loop.agent_manager._pre_plan_profile = BuiltinAgentName.DEFAULT
        loop.messages.append(
            type(loop.messages[0])(role=Role.user, content="planning chatter")
        )
        original_session_id = loop.session_id

        plan_text = "# Plan\n- Step 1\n- Step 2"
        plan_path = Path("/tmp/.vibe/plans/example.md")
        loop.request_fork_to_dev(plan_text, plan_path, BuiltinAgentName.DEFAULT)
        assert loop.pending_fork_to_dev is not None

        seed = await loop.fork_to_dev()

        # Seed contains the plan and the file path.
        assert "Implement the following plan" in seed
        assert plan_text in seed
        assert str(plan_path) in seed

        # Profile switched.
        assert loop.agent_profile.name == BuiltinAgentName.DEFAULT

        # History wiped — only the (refreshed) system prompt remains.
        assert len(loop.messages) == 1
        assert loop.messages[0].role == Role.system

        # Session ID regenerated; pending state cleared.
        assert loop.session_id != original_session_id
        assert loop.pending_fork_to_dev is None

    @pytest.mark.asyncio
    async def test_fork_without_pending_raises(self) -> None:
        config = build_test_vibe_config()
        loop = build_test_agent_loop(
            config=config, agent_name=BuiltinAgentName.PLAN
        )
        with pytest.raises(Exception):  # AgentLoopError
            await loop.fork_to_dev()

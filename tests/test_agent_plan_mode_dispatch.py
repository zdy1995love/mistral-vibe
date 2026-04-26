from __future__ import annotations

import json

import pytest

from tests.conftest import build_test_agent_loop, build_test_vibe_config
from tests.mock.utils import mock_llm_chunk
from tests.stubs.fake_backend import FakeBackend
from vibe.core.agents.models import BuiltinAgentName
from vibe.core.types import FunctionCall, ToolCall, ToolResultEvent

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

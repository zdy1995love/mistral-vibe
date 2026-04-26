from __future__ import annotations

from typing import Any

import pytest

from tests.mock.utils import collect_result
from vibe.core.agents.models import BuiltinAgentName
from vibe.core.tools.base import BaseToolState, InvokeContext, ToolError
from vibe.core.tools.builtins.enter_plan_mode import (
    EnterPlanMode,
    EnterPlanModeArgs,
    EnterPlanModeConfig,
    EnterPlanModeResult,
)


class _FakeProfile:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeAgentManager:
    def __init__(self, current: str = BuiltinAgentName.DEFAULT) -> None:
        self.active_profile = _FakeProfile(current)
        self.switched_to: str | None = None

    def switch_profile(self, name: str) -> None:
        self.active_profile = _FakeProfile(name)
        self.switched_to = name


class _FakeUserInput:
    """Mimics the AskUserQuestion callback. Returns a canned answer."""

    def __init__(self, answer_label: str, cancelled: bool = False) -> None:
        self._answer_label = answer_label
        self._cancelled = cancelled

    async def __call__(self, args: Any) -> Any:
        from vibe.core.tools.builtins.ask_user_question import (
            Answer,
            AskUserQuestionResult,
        )

        if self._cancelled:
            return AskUserQuestionResult(answers=[], cancelled=True)
        return AskUserQuestionResult(
            answers=[Answer(question="", answer=self._answer_label, is_other=False)],
            cancelled=False,
        )


def _make_tool() -> EnterPlanMode:
    return EnterPlanMode(
        config_getter=lambda: EnterPlanModeConfig(),
        state=BaseToolState(),
    )


class TestEnterPlanMode:
    def test_mutates_state_is_false(self) -> None:
        assert EnterPlanMode.mutates_state is False

    @pytest.mark.asyncio
    async def test_requires_agent_manager(self) -> None:
        tool = _make_tool()
        with pytest.raises(ToolError, match="agent manager"):
            await collect_result(
                tool.run(EnterPlanModeArgs(), ctx=InvokeContext(tool_call_id="t1"))
            )

    @pytest.mark.asyncio
    async def test_refuses_when_already_in_plan_mode(self) -> None:
        tool = _make_tool()
        ctx = InvokeContext(
            tool_call_id="t1",
            agent_manager=_FakeAgentManager(current=BuiltinAgentName.PLAN),  # type: ignore[arg-type]
        )
        with pytest.raises(ToolError, match="plan mode"):
            await collect_result(tool.run(EnterPlanModeArgs(), ctx=ctx))

    @pytest.mark.asyncio
    async def test_switches_to_plan_on_yes(self) -> None:
        tool = _make_tool()
        mgr = _FakeAgentManager()
        ctx = InvokeContext(
            tool_call_id="t1",
            agent_manager=mgr,  # type: ignore[arg-type]
            user_input_callback=_FakeUserInput("Yes, enter plan mode"),
        )
        result = await collect_result(tool.run(EnterPlanModeArgs(), ctx=ctx))
        assert isinstance(result, EnterPlanModeResult)
        assert result.switched is True
        assert mgr.switched_to == BuiltinAgentName.PLAN

    @pytest.mark.asyncio
    async def test_does_not_switch_on_no(self) -> None:
        tool = _make_tool()
        mgr = _FakeAgentManager()
        ctx = InvokeContext(
            tool_call_id="t1",
            agent_manager=mgr,  # type: ignore[arg-type]
            user_input_callback=_FakeUserInput("No"),
        )
        result = await collect_result(tool.run(EnterPlanModeArgs(), ctx=ctx))
        assert isinstance(result, EnterPlanModeResult)
        assert result.switched is False
        assert mgr.switched_to is None

    @pytest.mark.asyncio
    async def test_does_not_switch_when_user_cancels(self) -> None:
        tool = _make_tool()
        mgr = _FakeAgentManager()
        ctx = InvokeContext(
            tool_call_id="t1",
            agent_manager=mgr,  # type: ignore[arg-type]
            user_input_callback=_FakeUserInput("anything", cancelled=True),
        )
        result = await collect_result(tool.run(EnterPlanModeArgs(), ctx=ctx))
        assert result.switched is False
        assert mgr.switched_to is None

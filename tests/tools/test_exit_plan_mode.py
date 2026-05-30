from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel
import pytest

from tests.mock.utils import collect_result
from vibe.core.agents.models import AgentProfile, AgentSafety, BuiltinAgentName
from vibe.core.tools.base import BaseToolState, InvokeContext, ToolError
from vibe.core.tools.builtins.ask_user_question import (
    Answer,
    AskUserQuestionArgs,
    AskUserQuestionResult,
)
from vibe.core.tools.builtins.exit_plan_mode import (
    ExitPlanMode,
    ExitPlanModeArgs,
    ExitPlanModeConfig,
)


@dataclass
class MockAgentManager:
    active_profile: AgentProfile
    pre_plan_profile: str | None = None
    available_agents: dict[str, AgentProfile] = field(default_factory=dict)
    _switched_to: list[str] = field(default_factory=list)

    def switch_profile(self, name: str) -> None:
        self._switched_to.append(name)
        self.active_profile = AgentProfile(
            name=name,
            display_name=name.title(),
            description="",
            safety=AgentSafety.SAFE,
        )


def _plan_profile() -> AgentProfile:
    return AgentProfile(
        name=BuiltinAgentName.PLAN,
        display_name="Plan",
        description="Plan mode",
        safety=AgentSafety.SAFE,
    )


def _default_profile() -> AgentProfile:
    return AgentProfile(
        name=BuiltinAgentName.DEFAULT,
        display_name="Default",
        description="Default mode",
        safety=AgentSafety.SAFE,
    )


@pytest.fixture
def tool() -> ExitPlanMode:
    return ExitPlanMode(
        config_getter=lambda: ExitPlanModeConfig(), state=BaseToolState()
    )


@pytest.fixture
def plan_manager() -> MockAgentManager:
    return MockAgentManager(active_profile=_plan_profile())


@pytest.fixture
def plan_file(tmp_path: Path) -> Path:
    p = tmp_path / "plan.md"
    p.write_text("# My Plan\n\n- Step 1\n- Step 2\n")
    return p


class MockCallback:
    def __init__(self, result: AskUserQuestionResult) -> None:
        self._result = result
        self.received_args: BaseModel | None = None

    async def __call__(self, args: BaseModel) -> BaseModel:
        self.received_args = args
        return self._result


class MockForkToDevCallback:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Path, str]] = []

    def __call__(self, plan_text: str, plan_path: Path, target_profile: str) -> None:
        self.calls.append((plan_text, plan_path, target_profile))


def _yes_auto() -> AskUserQuestionResult:
    return AskUserQuestionResult(
        answers=[
            Answer(question="q", answer="Yes, and auto approve edits", is_other=False)
        ],
        cancelled=False,
    )


def _yes_request_approval() -> AskUserQuestionResult:
    return AskUserQuestionResult(
        answers=[
            Answer(
                question="q",
                answer="Yes, and request approval for edits",
                is_other=False,
            )
        ],
        cancelled=False,
    )


class TestErrorCases:
    @pytest.mark.asyncio
    async def test_requires_agent_manager(self, tool: ExitPlanMode) -> None:
        ctx = InvokeContext(
            tool_call_id="t1",
            user_input_callback=MockCallback(
                AskUserQuestionResult(answers=[], cancelled=True)
            ),
        )
        with pytest.raises(ToolError, match="agent manager"):
            await collect_result(tool.run(ExitPlanModeArgs(), ctx))

    @pytest.mark.asyncio
    async def test_requires_plan_mode(self, tool: ExitPlanMode) -> None:
        manager = MockAgentManager(active_profile=_default_profile())
        ctx = InvokeContext(
            tool_call_id="t1",
            agent_manager=manager,  # type: ignore[arg-type]
            user_input_callback=MockCallback(
                AskUserQuestionResult(answers=[], cancelled=True)
            ),
        )
        with pytest.raises(ToolError, match="plan mode"):
            await collect_result(tool.run(ExitPlanModeArgs(), ctx))

    @pytest.mark.asyncio
    async def test_requires_interactive_ui(
        self, tool: ExitPlanMode, plan_manager: MockAgentManager, plan_file: Path
    ) -> None:
        ctx = InvokeContext(
            tool_call_id="t1",
            agent_manager=plan_manager,  # type: ignore[arg-type]
            plan_file_path=plan_file,
        )
        with pytest.raises(ToolError, match="interactive UI"):
            await collect_result(tool.run(ExitPlanModeArgs(), ctx))

    @pytest.mark.asyncio
    async def test_rejects_when_no_plan_file_path(
        self, tool: ExitPlanMode, plan_manager: MockAgentManager
    ) -> None:
        ctx = InvokeContext(
            tool_call_id="t1",
            agent_manager=plan_manager,  # type: ignore[arg-type]
            user_input_callback=MockCallback(_yes_auto()),
            plan_file_path=None,
        )
        with pytest.raises(ToolError, match="No plan file found"):
            await collect_result(tool.run(ExitPlanModeArgs(), ctx))

    @pytest.mark.asyncio
    async def test_rejects_when_plan_file_missing(
        self, tool: ExitPlanMode, plan_manager: MockAgentManager, tmp_path: Path
    ) -> None:
        ctx = InvokeContext(
            tool_call_id="t1",
            agent_manager=plan_manager,  # type: ignore[arg-type]
            user_input_callback=MockCallback(_yes_auto()),
            plan_file_path=tmp_path / "does-not-exist.md",
        )
        with pytest.raises(ToolError, match="No plan file found"):
            await collect_result(tool.run(ExitPlanModeArgs(), ctx))

    @pytest.mark.asyncio
    async def test_rejects_when_plan_file_empty(
        self, tool: ExitPlanMode, plan_manager: MockAgentManager, tmp_path: Path
    ) -> None:
        empty = tmp_path / "empty.md"
        empty.write_text("   \n\n")
        ctx = InvokeContext(
            tool_call_id="t1",
            agent_manager=plan_manager,  # type: ignore[arg-type]
            user_input_callback=MockCallback(_yes_auto()),
            plan_file_path=empty,
        )
        with pytest.raises(ToolError, match="empty"):
            await collect_result(tool.run(ExitPlanModeArgs(), ctx))


class TestRecentPlanFallback:
    """If ctx.plan_file_path is missing-on-disk but a recent <ts>-<slug>.md
    sits in PLANS_DIR (cwd-relative), exit_plan_mode falls back to it
    instead of raising. Recovers from the path-drift bug where
    PlanSession's cached path mismatches what the LLM actually wrote.
    """

    @pytest.mark.asyncio
    async def test_fallback_picks_recent_plan_file_when_ctx_missing(
        self, tool: ExitPlanMode, plan_manager: MockAgentManager, tmp_path: Path
    ) -> None:
        from vibe.core.paths import PLANS_DIR
        plans_dir = PLANS_DIR.path
        plans_dir.mkdir(parents=True, exist_ok=True)
        recent = plans_dir / "1700000000-fresh-bright-stone.md"
        recent.write_text("# My Plan\nReal content.\n")

        fork_cb = MockForkToDevCallback()
        ctx = InvokeContext(
            tool_call_id="t1",
            agent_manager=plan_manager,  # type: ignore[arg-type]
            user_input_callback=MockCallback(_yes_auto()),
            plan_file_path=tmp_path / "stale-cached-path.md",  # doesn't exist
            request_fork_to_dev_callback=fork_cb,
        )
        result = await collect_result(tool.run(ExitPlanModeArgs(), ctx))
        assert result.switched is True
        plan_text, plan_path, _profile = fork_cb.calls[0]
        assert plan_path == recent
        assert "My Plan" in plan_text

    @pytest.mark.asyncio
    async def test_fallback_skips_old_files_outside_window(
        self, tool: ExitPlanMode, plan_manager: MockAgentManager, tmp_path: Path
    ) -> None:
        import os

        from vibe.core.paths import PLANS_DIR
        plans_dir = PLANS_DIR.path
        plans_dir.mkdir(parents=True, exist_ok=True)
        old = plans_dir / "1700000000-old-aged-stone.md"
        old.write_text("# stale\n")
        # Backdate mtime to >24h ago (outside the fallback window)
        old_ts = old.stat().st_mtime - 25 * 3600
        os.utime(old, (old_ts, old_ts))

        ctx = InvokeContext(
            tool_call_id="t1",
            agent_manager=plan_manager,  # type: ignore[arg-type]
            user_input_callback=MockCallback(_yes_auto()),
            plan_file_path=tmp_path / "stale-cached-path.md",
        )
        with pytest.raises(ToolError, match="No plan file found"):
            await collect_result(tool.run(ExitPlanModeArgs(), ctx))

    @pytest.mark.asyncio
    async def test_fallback_ignores_non_pattern_files(
        self, tool: ExitPlanMode, plan_manager: MockAgentManager, tmp_path: Path
    ) -> None:
        from vibe.core.paths import PLANS_DIR
        plans_dir = PLANS_DIR.path
        plans_dir.mkdir(parents=True, exist_ok=True)
        bogus = plans_dir / "notes.md"  # doesn't match <ts>-<slug>.md
        bogus.write_text("# Notes\n")

        ctx = InvokeContext(
            tool_call_id="t1",
            agent_manager=plan_manager,  # type: ignore[arg-type]
            user_input_callback=MockCallback(_yes_auto()),
            plan_file_path=tmp_path / "stale-cached-path.md",
        )
        with pytest.raises(ToolError, match="No plan file found"):
            await collect_result(tool.run(ExitPlanModeArgs(), ctx))


class TestForkOnApproval:
    @pytest.mark.asyncio
    async def test_yes_auto_forks_to_accept_edits(
        self, tool: ExitPlanMode, plan_manager: MockAgentManager, plan_file: Path
    ) -> None:
        fork_cb = MockForkToDevCallback()
        ctx = InvokeContext(
            tool_call_id="t1",
            agent_manager=plan_manager,  # type: ignore[arg-type]
            user_input_callback=MockCallback(_yes_auto()),
            plan_file_path=plan_file,
            request_fork_to_dev_callback=fork_cb,
        )
        result = await collect_result(tool.run(ExitPlanModeArgs(), ctx))
        assert result.switched is True
        assert len(fork_cb.calls) == 1
        plan_text, plan_path, target_profile = fork_cb.calls[0]
        assert "My Plan" in plan_text
        assert plan_path == plan_file
        assert target_profile == BuiltinAgentName.ACCEPT_EDITS

    @pytest.mark.asyncio
    async def test_yes_request_approval_uses_pre_plan_profile(
        self, tool: ExitPlanMode, plan_file: Path
    ) -> None:
        manager = MockAgentManager(
            active_profile=_plan_profile(),
            pre_plan_profile=BuiltinAgentName.AUTO_APPROVE,
            available_agents={
                BuiltinAgentName.AUTO_APPROVE: AgentProfile(
                    name=BuiltinAgentName.AUTO_APPROVE,
                    display_name="Auto",
                    description="",
                    safety=AgentSafety.SAFE,
                )
            },
        )
        fork_cb = MockForkToDevCallback()
        ctx = InvokeContext(
            tool_call_id="t1",
            agent_manager=manager,  # type: ignore[arg-type]
            user_input_callback=MockCallback(_yes_request_approval()),
            plan_file_path=plan_file,
            request_fork_to_dev_callback=fork_cb,
        )
        result = await collect_result(tool.run(ExitPlanModeArgs(), ctx))
        assert result.switched is True
        assert fork_cb.calls[0][2] == BuiltinAgentName.AUTO_APPROVE

    @pytest.mark.asyncio
    async def test_yes_request_approval_falls_back_when_pre_plan_profile_missing(
        self, tool: ExitPlanMode, plan_file: Path
    ) -> None:
        """Defensive: pre_plan_profile may have been removed (custom agent
        toml deleted) while user was in plan mode. Falls back to DEFAULT.
        """
        manager = MockAgentManager(
            active_profile=_plan_profile(),
            pre_plan_profile="some-deleted-custom-agent",
            available_agents={},  # the named profile is no longer present
        )
        fork_cb = MockForkToDevCallback()
        ctx = InvokeContext(
            tool_call_id="t1",
            agent_manager=manager,  # type: ignore[arg-type]
            user_input_callback=MockCallback(_yes_request_approval()),
            plan_file_path=plan_file,
            request_fork_to_dev_callback=fork_cb,
        )
        result = await collect_result(tool.run(ExitPlanModeArgs(), ctx))
        assert result.switched is True
        assert fork_cb.calls[0][2] == BuiltinAgentName.DEFAULT

    @pytest.mark.asyncio
    async def test_yes_request_approval_falls_back_to_default(
        self, tool: ExitPlanMode, plan_manager: MockAgentManager, plan_file: Path
    ) -> None:
        # plan_manager has pre_plan_profile=None
        fork_cb = MockForkToDevCallback()
        ctx = InvokeContext(
            tool_call_id="t1",
            agent_manager=plan_manager,  # type: ignore[arg-type]
            user_input_callback=MockCallback(_yes_request_approval()),
            plan_file_path=plan_file,
            request_fork_to_dev_callback=fork_cb,
        )
        result = await collect_result(tool.run(ExitPlanModeArgs(), ctx))
        assert result.switched is True
        assert fork_cb.calls[0][2] == BuiltinAgentName.DEFAULT

    @pytest.mark.asyncio
    async def test_yes_without_fork_callback_errors(
        self, tool: ExitPlanMode, plan_manager: MockAgentManager, plan_file: Path
    ) -> None:
        ctx = InvokeContext(
            tool_call_id="t1",
            agent_manager=plan_manager,  # type: ignore[arg-type]
            user_input_callback=MockCallback(_yes_auto()),
            plan_file_path=plan_file,
            request_fork_to_dev_callback=None,
        )
        with pytest.raises(ToolError, match="Fork-to-dev not available"):
            await collect_result(tool.run(ExitPlanModeArgs(), ctx))


class TestNoFork:
    @pytest.mark.asyncio
    async def test_no_stays_in_plan_mode(
        self, tool: ExitPlanMode, plan_manager: MockAgentManager, plan_file: Path
    ) -> None:
        fork_cb = MockForkToDevCallback()
        cb = MockCallback(
            AskUserQuestionResult(
                answers=[Answer(question="q", answer="No", is_other=False)],
                cancelled=False,
            )
        )
        ctx = InvokeContext(
            tool_call_id="t1",
            agent_manager=plan_manager,  # type: ignore[arg-type]
            user_input_callback=cb,
            plan_file_path=plan_file,
            request_fork_to_dev_callback=fork_cb,
        )
        result = await collect_result(tool.run(ExitPlanModeArgs(), ctx))
        assert result.switched is False
        assert fork_cb.calls == []

    @pytest.mark.asyncio
    async def test_cancelled_stays(
        self, tool: ExitPlanMode, plan_manager: MockAgentManager, plan_file: Path
    ) -> None:
        fork_cb = MockForkToDevCallback()
        cb = MockCallback(AskUserQuestionResult(answers=[], cancelled=True))
        ctx = InvokeContext(
            tool_call_id="t1",
            agent_manager=plan_manager,  # type: ignore[arg-type]
            user_input_callback=cb,
            plan_file_path=plan_file,
            request_fork_to_dev_callback=fork_cb,
        )
        result = await collect_result(tool.run(ExitPlanModeArgs(), ctx))
        assert result.switched is False
        assert fork_cb.calls == []

    @pytest.mark.asyncio
    async def test_other_includes_feedback(
        self, tool: ExitPlanMode, plan_manager: MockAgentManager, plan_file: Path
    ) -> None:
        fork_cb = MockForkToDevCallback()
        cb = MockCallback(
            AskUserQuestionResult(
                answers=[
                    Answer(question="q", answer="Add error handling", is_other=True)
                ],
                cancelled=False,
            )
        )
        ctx = InvokeContext(
            tool_call_id="t1",
            agent_manager=plan_manager,  # type: ignore[arg-type]
            user_input_callback=cb,
            plan_file_path=plan_file,
            request_fork_to_dev_callback=fork_cb,
        )
        result = await collect_result(tool.run(ExitPlanModeArgs(), ctx))
        assert result.switched is False
        # Message must contain (a) the user's verbatim feedback and (b) an
        # explicit instruction to update the plan file before retrying —
        # without that, some models loop on exit_plan_mode without acting
        # on the feedback.
        assert "Add error handling" in result.message
        assert "ACTION REQUIRED" in result.message
        assert "update the plan file" in result.message
        assert str(plan_file) in result.message
        assert fork_cb.calls == []


class TestPlanFilePreview:
    @pytest.mark.asyncio
    async def test_plan_path_in_footer_note(
        self, tool: ExitPlanMode, plan_manager: MockAgentManager, plan_file: Path
    ) -> None:
        # v2.13's AskUserQuestionArgs has no content_preview field; the plan
        # path (with the Ctrl+G hint) is surfaced via footer_note instead.
        cb = MockCallback(AskUserQuestionResult(answers=[], cancelled=True))
        ctx = InvokeContext(
            tool_call_id="t1",
            agent_manager=plan_manager,  # type: ignore[arg-type]
            user_input_callback=cb,
            plan_file_path=plan_file,
        )
        await collect_result(tool.run(ExitPlanModeArgs(), ctx))
        assert isinstance(cb.received_args, AskUserQuestionArgs)
        assert cb.received_args.footer_note is not None
        assert str(plan_file) in cb.received_args.footer_note

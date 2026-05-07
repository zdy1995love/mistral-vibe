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
                                arguments=json.dumps({
                                    "agent": "explore",
                                    "task": "find foo",
                                }),
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
    async def test_read_only_bash_allowed_in_plan_mode(self) -> None:
        """Plan mode allows read-only bash commands (ls, find, grep, git log,
        etc.) so the LLM can explore the repo while planning. Anything not
        on the read-only allowlist stays blocked.
        """
        backend = FakeBackend([
            [
                mock_llm_chunk(
                    tool_calls=[
                        ToolCall(
                            id="call_1",
                            index=0,
                            function=FunctionCall(
                                name="bash", arguments=json.dumps({"command": "ls"})
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

        events = [e async for e in loop.act("explore")]
        tool_results = [e for e in events if isinstance(e, ToolResultEvent)]

        assert len(tool_results) == 1
        # Gate should NOT have fired — `ls` is allowlisted in plan mode.
        assert PLAN_MODE_ERROR not in (tool_results[0].error or "")

    @pytest.mark.asyncio
    async def test_non_allowlisted_bash_blocked_in_plan_mode(self) -> None:
        """Bash commands outside the plan-mode read-only allowlist (e.g.
        `rm`, `git commit`) stay blocked.
        """
        backend = FakeBackend([
            [
                mock_llm_chunk(
                    tool_calls=[
                        ToolCall(
                            id="call_1",
                            index=0,
                            function=FunctionCall(
                                name="bash",
                                arguments=json.dumps({"command": "rm -rf /tmp/foo"}),
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

        events = [e async for e in loop.act("delete a file")]
        tool_results = [e for e in events if isinstance(e, ToolResultEvent)]

        assert len(tool_results) == 1
        assert PLAN_MODE_ERROR in (tool_results[0].error or "")

    @pytest.mark.asyncio
    async def test_write_to_plan_path_allowed_in_plan_mode(self) -> None:
        """The PLAN profile's allowlist for plans_dir/* must actually take
        effect: the LLM must be able to author the plan file the system
        reminder told it to write. resolve_permission returns ALWAYS for
        plan paths, and the dispatch gate bypasses on ALWAYS.
        """
        from vibe.core.paths import PLANS_DIR

        plan_path = PLANS_DIR.path / "test-plan.md"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        backend = FakeBackend([
            [
                mock_llm_chunk(
                    tool_calls=[
                        _write_file_tool_call(str(plan_path), content="# Plan\n")
                    ]
                )
            ],
            [mock_llm_chunk(content="done")],
        ])
        config = build_test_vibe_config()
        loop = build_test_agent_loop(
            config=config, agent_name=BuiltinAgentName.PLAN, backend=backend
        )

        events = [e async for e in loop.act("write the plan")]
        tool_results = [e for e in events if isinstance(e, ToolResultEvent)]

        assert len(tool_results) == 1
        # Gate must NOT have fired — write to plan path is allowlisted.
        assert PLAN_MODE_ERROR not in (tool_results[0].error or "")
        assert plan_path.exists()
        assert plan_path.read_text() == "# Plan\n"

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
        loop = build_test_agent_loop(config=config, agent_name=BuiltinAgentName.PLAN)
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
        loop = build_test_agent_loop(config=config, agent_name=BuiltinAgentName.PLAN)
        with pytest.raises(Exception):  # AgentLoopError
            await loop.fork_to_dev()

    @pytest.mark.asyncio
    async def test_fork_rotates_plan_session(self) -> None:
        """A second /plan after fork must write to a new file, not overwrite
        the just-approved plan.
        """
        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config, agent_name=BuiltinAgentName.PLAN)
        original_plan_path = loop._plan_session.plan_file_path

        loop.request_fork_to_dev("# Plan", original_plan_path, BuiltinAgentName.DEFAULT)
        await loop.fork_to_dev()

        # Plan session should be a fresh instance with an unevaluated path.
        assert loop._plan_session._plan_file_path is None
        # First access of the new plan_session yields a different path.
        new_plan_path = loop._plan_session.plan_file_path
        assert new_plan_path != original_plan_path

    @pytest.mark.asyncio
    async def test_plan_session_rotates_on_cancel_toggle_out(self) -> None:
        """Bug regression: /plan toggle out of PLAN (cancel) must rotate
        plan_session so a re-entry into PLAN gets a fresh {ts}-{slug}.md
        path. Otherwise the second plan would overwrite the first.
        """
        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config, agent_name=BuiltinAgentName.PLAN)
        # Force lazy-evaluation of the plan path (simulates LLM having
        # written or referenced the plan file during the first plan turn).
        first_path = loop._plan_session.plan_file_path
        first_session_obj = loop._plan_session

        # Simulate /plan cancel: switch back to DEFAULT.
        await loop.switch_agent(BuiltinAgentName.DEFAULT)

        # plan_session must be a NEW instance with no cached path.
        assert loop._plan_session is not first_session_obj
        assert loop._plan_session._plan_file_path is None

        # Re-enter PLAN, force evaluation, expect a different path.
        await loop.switch_agent(BuiltinAgentName.PLAN)
        second_path = loop._plan_session.plan_file_path
        assert second_path != first_path

    @pytest.mark.asyncio
    async def test_plan_session_unchanged_when_not_leaving_plan(self) -> None:
        """Switching between non-PLAN profiles (DEFAULT ↔ ACCEPT_EDITS)
        must NOT rotate plan_session — only leaving PLAN does.
        """
        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config, agent_name=BuiltinAgentName.DEFAULT)
        original_session = loop._plan_session
        await loop.switch_agent(BuiltinAgentName.ACCEPT_EDITS)
        assert loop._plan_session is original_session

    @pytest.mark.asyncio
    async def test_fork_clears_pending_before_state_mutation(self) -> None:
        """Cancel-safety: pending_fork_to_dev is cleared up-front so a
        partial-fork doesn't leave the host's loop spinning.
        """
        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config, agent_name=BuiltinAgentName.PLAN)
        loop.request_fork_to_dev("# Plan", Path("/tmp/p.md"), BuiltinAgentName.DEFAULT)
        assert loop.pending_fork_to_dev is not None
        await loop.fork_to_dev()
        # After (or even mid-) fork, pending must be cleared.
        assert loop.pending_fork_to_dev is None


class TestFullForkFlowEndToEnd:
    """End-to-end: plan mode LLM calls ExitPlanMode → user approves → loop
    signals pending fork → fork_to_dev clears + switches + returns seed →
    re-act with seed in pre-plan profile.
    """

    @pytest.mark.asyncio
    async def test_exit_plan_mode_to_fork_to_dev_then_implement(self) -> None:
        from vibe.core.tools.builtins.ask_user_question import (
            Answer,
            AskUserQuestionResult,
        )
        from vibe.core.types import AssistantEvent

        config = build_test_vibe_config()
        backend = FakeBackend([
            # Turn 1 (PLAN): LLM calls ExitPlanMode
            [
                mock_llm_chunk(
                    tool_calls=[
                        ToolCall(
                            id="call_1",
                            index=0,
                            function=FunctionCall(
                                name="exit_plan_mode", arguments="{}"
                            ),
                        )
                    ]
                )
            ],
            # Turn 2 (DEFAULT, post-fork): LLM responds to seed
            [mock_llm_chunk(content="Implementing now.")],
        ])
        loop = build_test_agent_loop(
            config=config, agent_name=BuiltinAgentName.PLAN, backend=backend
        )
        # Mark DEFAULT as pre_plan so fork lands there.
        loop.agent_manager._pre_plan_profile = BuiltinAgentName.DEFAULT

        # Pre-write the plan file at the path the loop will check.
        plan_file = loop._plan_session.plan_file_path
        plan_file.parent.mkdir(parents=True, exist_ok=True)
        plan_text = "# Plan\n- step 1\n"
        plan_file.write_text(plan_text)

        async def approve(_args: object) -> AskUserQuestionResult:
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

        loop.set_user_input_callback(approve)

        # Drive PLAN turn — ExitPlanMode runs, fork is staged, loop breaks.
        original_session_id = loop.session_id
        events_1 = [e async for e in loop.act("exit when ready")]
        assert loop.pending_fork_to_dev is not None
        # ExitPlanMode tool result is in events_1, but no DEFAULT-profile
        # response yet (loop broke out before the second LLM turn).
        assert isinstance(events_1, list)

        # Drive fork — would be done by host app after act() returns.
        seed = await loop.fork_to_dev()
        assert plan_text.strip() in seed
        assert str(plan_file) in seed
        assert loop.agent_profile.name == BuiltinAgentName.DEFAULT
        assert loop.session_id != original_session_id  # new session
        assert len(loop.messages) == 1  # only system prompt

        # Drive DEFAULT turn with seed — LLM implements.
        events_2 = [e async for e in loop.act(seed)]
        assistant_replies = [e for e in events_2 if isinstance(e, AssistantEvent)]
        assert any("Implementing now" in (e.content or "") for e in assistant_replies)
        # Plan file persists on disk through the fork.
        assert plan_file.is_file()


class TestAutoPlanConfirmPopup:
    """The plan-confirmation popup must fire SOFTWARE-driven, not by waiting
    for the LLM to call exit_plan_mode. Trigger: in PLAN profile, after a
    write_file/search_replace mutates the plan file, once the LLM's
    current turn drains (no more tool_calls), agent_loop invokes
    user_input_callback with the same 3-option AskUserQuestion the
    ExitPlanMode tool uses. On approval, fork-to-dev is staged.
    """

    @pytest.mark.asyncio
    async def test_auto_popup_after_plan_write_and_turn_settles(self) -> None:
        from vibe.core.tools.builtins.ask_user_question import (
            Answer,
            AskUserQuestionArgs,
            AskUserQuestionResult,
        )

        config = build_test_vibe_config()
        loop = build_test_agent_loop(
            config=config, agent_name=BuiltinAgentName.PLAN, backend=FakeBackend([])
        )
        plan_path = loop._plan_session.plan_file_path
        plan_path.parent.mkdir(parents=True, exist_ok=True)

        # Two-turn script: write_file targets the canonical plan path; LLM
        # then produces a final assistant message with NO tool_calls — the
        # natural moment when the auto-popup should fire.
        write_args = json.dumps({
            "path": str(plan_path),
            "content": "# Plan\n- step 1\n- step 2\n",
        })
        loop.backend = FakeBackend([
            [
                mock_llm_chunk(
                    tool_calls=[
                        ToolCall(
                            id="call_1",
                            index=0,
                            function=FunctionCall(
                                name="write_file", arguments=write_args
                            ),
                        )
                    ]
                )
            ],
            [mock_llm_chunk(content="Plan summary written.")],
        ])
        loop.agent_manager._pre_plan_profile = BuiltinAgentName.DEFAULT

        captured_questions: list[AskUserQuestionArgs] = []

        async def approve(args: AskUserQuestionArgs) -> AskUserQuestionResult:
            captured_questions.append(args)
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

        loop.set_user_input_callback(approve)

        events = [e async for e in loop.act("write the plan")]
        assert events  # smoke: events flowed

        # The popup must have fired exactly once when the LLM's tool chain
        # settled — software-driven, not waiting for an exit_plan_mode call.
        assert len(captured_questions) == 1, (
            f"Expected auto-popup to fire once when plan was written + turn "
            f"settled, got {len(captured_questions)} popup(s)"
        )
        q = captured_questions[0].questions[0]
        # Same 3-option shape as ExitPlanMode.
        labels = {opt.label for opt in q.options}
        assert "Yes, and auto approve edits" in labels
        assert "Yes, and request approval for edits" in labels

        # On approval, fork-to-dev must be staged exactly like
        # ExitPlanMode would do.
        assert loop.pending_fork_to_dev is not None
        plan_text, staged_path, target = loop.pending_fork_to_dev
        assert "step 1" in plan_text
        assert staged_path == plan_path
        assert target == BuiltinAgentName.DEFAULT  # pre_plan_profile

    @pytest.mark.asyncio
    async def test_auto_popup_does_not_fire_when_plan_unchanged(self) -> None:
        """Read-only turns in plan mode must not trigger the popup; only
        write_file/search_replace against the plan path arms it."""
        from vibe.core.tools.builtins.ask_user_question import (
            AskUserQuestionArgs,
            AskUserQuestionResult,
        )

        config = build_test_vibe_config()
        loop = build_test_agent_loop(
            config=config, agent_name=BuiltinAgentName.PLAN, backend=FakeBackend([])
        )

        # LLM does only read_file then summarises — no plan write.
        target_file = Path(loop._plan_session.plan_file_path).parent / "noop.txt"
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_text("hello")
        loop.backend = FakeBackend([
            [mock_llm_chunk(tool_calls=[_read_file_tool_call(str(target_file))])],
            [mock_llm_chunk(content="Just exploring, no plan yet.")],
        ])

        called: list[AskUserQuestionArgs] = []

        async def callback(args: AskUserQuestionArgs) -> AskUserQuestionResult:
            called.append(args)
            return AskUserQuestionResult(answers=[], cancelled=True)

        loop.set_user_input_callback(callback)

        list(await _drain(loop.act("explore")))
        assert called == [], (
            f"Auto-popup must not fire on read-only turns; got {len(called)} call(s)"
        )
        assert loop.pending_fork_to_dev is None


async def _drain(agen):
    return [e async for e in agen]

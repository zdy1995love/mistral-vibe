from __future__ import annotations

import pytest

from tests.conftest import build_test_agent_loop, build_test_vibe_config
from vibe.core.agents.models import BUILTIN_AGENTS, CHAT, AgentProfile, BuiltinAgentName
from vibe.core.compact.micro import MicroCompactMiddleware
from vibe.core.config import VibeConfig
from vibe.core.middleware import (
    CHAT_AGENT_EXIT,
    CHAT_AGENT_REMINDER,
    PLAN_AGENT_EXIT,
    ConversationContext,
    MiddlewareAction,
    MiddlewarePipeline,
    ReadOnlyAgentMiddleware,
    ResetReason,
    make_plan_agent_reminder,
)
from vibe.core.types import AgentStats, LLMMessage, MessageList, Role

REMINDER = "test reminder"
EXIT_MSG = "test exit"
TARGET_AGENT = BuiltinAgentName.PLAN


def _build_middleware(
    profile_getter,
    agent_name: str = TARGET_AGENT,
    reminder: str = REMINDER,
    exit_message: str = EXIT_MSG,
) -> ReadOnlyAgentMiddleware:
    return ReadOnlyAgentMiddleware(profile_getter, agent_name, reminder, exit_message)


@pytest.fixture
def ctx(vibe_config: VibeConfig) -> ConversationContext:
    return ConversationContext(
        messages=MessageList(), stats=AgentStats(), config=vibe_config
    )


class TestReadOnlyAgentMiddleware:
    @pytest.mark.asyncio
    async def test_injects_reminder_when_target_agent_active(
        self, ctx: ConversationContext
    ) -> None:
        middleware = _build_middleware(lambda: BUILTIN_AGENTS[BuiltinAgentName.PLAN])

        result = await middleware.before_turn(ctx)

        assert result.action == MiddlewareAction.INJECT_MESSAGE
        assert result.message == REMINDER

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "agent_name",
        [
            BuiltinAgentName.DEFAULT,
            BuiltinAgentName.AUTO_APPROVE,
            BuiltinAgentName.ACCEPT_EDITS,
        ],
    )
    async def test_does_not_inject_when_non_target_agent(
        self, ctx: ConversationContext, agent_name: str
    ) -> None:
        middleware = _build_middleware(lambda: BUILTIN_AGENTS[agent_name])

        result = await middleware.before_turn(ctx)

        assert result.action == MiddlewareAction.CONTINUE
        assert result.message is None

    @pytest.mark.asyncio
    async def test_injects_reminder_only_once(self, ctx: ConversationContext) -> None:
        middleware = _build_middleware(lambda: BUILTIN_AGENTS[BuiltinAgentName.PLAN])

        result1 = await middleware.before_turn(ctx)
        assert result1.action == MiddlewareAction.INJECT_MESSAGE
        assert result1.message == REMINDER

        result2 = await middleware.before_turn(ctx)
        assert result2.action == MiddlewareAction.CONTINUE
        assert result2.message is None

    @pytest.mark.asyncio
    async def test_injects_exit_message_when_leaving(
        self, ctx: ConversationContext
    ) -> None:
        current_profile: AgentProfile = BUILTIN_AGENTS[BuiltinAgentName.PLAN]
        middleware = _build_middleware(lambda: current_profile)

        await middleware.before_turn(ctx)

        current_profile = BUILTIN_AGENTS[BuiltinAgentName.DEFAULT]
        result = await middleware.before_turn(ctx)
        assert result.action == MiddlewareAction.INJECT_MESSAGE
        assert result.message == EXIT_MSG

    @pytest.mark.asyncio
    async def test_reinjects_reminder_on_reentry(
        self, ctx: ConversationContext
    ) -> None:
        current_profile: AgentProfile = BUILTIN_AGENTS[BuiltinAgentName.PLAN]
        middleware = _build_middleware(lambda: current_profile)

        result1 = await middleware.before_turn(ctx)
        assert result1.action == MiddlewareAction.INJECT_MESSAGE
        assert result1.message == REMINDER

        current_profile = BUILTIN_AGENTS[BuiltinAgentName.DEFAULT]
        result2 = await middleware.before_turn(ctx)
        assert result2.action == MiddlewareAction.INJECT_MESSAGE
        assert result2.message == EXIT_MSG

        current_profile = BUILTIN_AGENTS[BuiltinAgentName.PLAN]
        result3 = await middleware.before_turn(ctx)
        assert result3.action == MiddlewareAction.INJECT_MESSAGE
        assert result3.message == REMINDER

    @pytest.mark.asyncio
    async def test_custom_reminder(self, ctx: ConversationContext) -> None:
        custom_reminder = "Custom reminder"
        middleware = _build_middleware(
            lambda: BUILTIN_AGENTS[BuiltinAgentName.PLAN], reminder=custom_reminder
        )

        result = await middleware.before_turn(ctx)

        assert result.message == custom_reminder

    @pytest.mark.asyncio
    async def test_custom_exit_message(self, ctx: ConversationContext) -> None:
        custom_exit = "Custom exit message"
        current_profile: AgentProfile = BUILTIN_AGENTS[BuiltinAgentName.PLAN]
        middleware = _build_middleware(
            lambda: current_profile, exit_message=custom_exit
        )

        await middleware.before_turn(ctx)

        current_profile = BUILTIN_AGENTS[BuiltinAgentName.DEFAULT]
        result = await middleware.before_turn(ctx)
        assert result.message == custom_exit

    @pytest.mark.asyncio
    async def test_reset_clears_state(self, ctx: ConversationContext) -> None:
        middleware = _build_middleware(lambda: BUILTIN_AGENTS[BuiltinAgentName.PLAN])
        await middleware.before_turn(ctx)

        middleware.reset()

        result = await middleware.before_turn(ctx)
        assert result.action == MiddlewareAction.INJECT_MESSAGE

    @pytest.mark.asyncio
    async def test_exit_message_fires_only_once(self, ctx: ConversationContext) -> None:
        current_profile: AgentProfile = BUILTIN_AGENTS[BuiltinAgentName.PLAN]
        middleware = _build_middleware(lambda: current_profile)

        await middleware.before_turn(ctx)

        current_profile = BUILTIN_AGENTS[BuiltinAgentName.DEFAULT]
        result = await middleware.before_turn(ctx)
        assert result.action == MiddlewareAction.INJECT_MESSAGE
        assert result.message == EXIT_MSG

        result2 = await middleware.before_turn(ctx)
        assert result2.action == MiddlewareAction.CONTINUE
        assert result2.message is None

    @pytest.mark.asyncio
    async def test_multiple_turns_after_entry(self, ctx: ConversationContext) -> None:
        middleware = _build_middleware(lambda: BUILTIN_AGENTS[BuiltinAgentName.PLAN])

        result = await middleware.before_turn(ctx)
        assert result.action == MiddlewareAction.INJECT_MESSAGE

        for _ in range(5):
            result = await middleware.before_turn(ctx)
            assert result.action == MiddlewareAction.CONTINUE
            assert result.message is None

    @pytest.mark.asyncio
    async def test_sparse_reminder_fires_periodically_while_active(
        self, ctx: ConversationContext
    ) -> None:
        middleware = ReadOnlyAgentMiddleware(
            lambda: BUILTIN_AGENTS[BuiltinAgentName.PLAN],
            BuiltinAgentName.PLAN,
            REMINDER,
            EXIT_MSG,
            sparse_reminder="sparse-msg",
            sparse_every_n_turns=3,
        )

        # Turn 1: entry — full reminder
        r = await middleware.before_turn(ctx)
        assert r.action == MiddlewareAction.INJECT_MESSAGE
        assert r.message == REMINDER

        # Turns 2..3: continue, no injection
        for _ in range(2):
            r = await middleware.before_turn(ctx)
            assert r.action == MiddlewareAction.CONTINUE

        # Turn 4: 3 turns since last reminder → sparse fires
        r = await middleware.before_turn(ctx)
        assert r.action == MiddlewareAction.INJECT_MESSAGE
        assert r.message == "sparse-msg"

        # Turns 5..6: continue
        for _ in range(2):
            r = await middleware.before_turn(ctx)
            assert r.action == MiddlewareAction.CONTINUE

        # Turn 7: another sparse fire
        r = await middleware.before_turn(ctx)
        assert r.action == MiddlewareAction.INJECT_MESSAGE
        assert r.message == "sparse-msg"

    @pytest.mark.asyncio
    async def test_sparse_reminder_disabled_by_default(
        self, ctx: ConversationContext
    ) -> None:
        middleware = _build_middleware(lambda: BUILTIN_AGENTS[BuiltinAgentName.PLAN])
        await middleware.before_turn(ctx)  # entry full
        for _ in range(20):
            r = await middleware.before_turn(ctx)
            assert r.action == MiddlewareAction.CONTINUE
            assert r.message is None

    @pytest.mark.asyncio
    async def test_sparse_reminder_skipped_when_prev_message_is_tool(
        self, vibe_config: VibeConfig
    ) -> None:
        """Strict backends (Mistral via vLLM) reject [tool, user] sequences.
        The agent_loop's middleware-result handler must skip Role.user
        injections when the last message is a tool result.

        Tested at the agent_loop integration level since the skip lives
        in agent_loop._handle_middleware_result, not in middleware itself.
        """
        from tests.conftest import build_test_agent_loop, build_test_vibe_config
        from vibe.core.types import LLMMessage, Role
        from vibe.core.middleware import (
            ConversationContext,
            MiddlewareAction,
            MiddlewareResult,
        )

        cfg = build_test_vibe_config()
        loop = build_test_agent_loop(config=cfg)
        # Seed messages so last is a tool result.
        loop.messages.append(LLMMessage(role=Role.user, content="hi"))
        loop.messages.append(LLMMessage(role=Role.assistant, content="ok"))
        loop.messages.append(LLMMessage(role=Role.tool, content="result"))
        prev_count = len(loop.messages)

        result = MiddlewareResult(
            action=MiddlewareAction.INJECT_MESSAGE, message="reminder"
        )
        async for _ in loop._handle_middleware_result(result):
            pass

        # No injection should have happened (last was tool).
        assert len(loop.messages) == prev_count

        # Now last is assistant — injection IS allowed.
        loop.messages.append(LLMMessage(role=Role.assistant, content="next"))
        prev_count = len(loop.messages)
        async for _ in loop._handle_middleware_result(result):
            pass
        assert len(loop.messages) == prev_count + 1
        assert loop.messages[-1].role == Role.user
        assert loop.messages[-1].content == "reminder"

    @pytest.mark.asyncio
    async def test_sparse_reminder_resets_on_exit_and_reentry(
        self, ctx: ConversationContext
    ) -> None:
        current_profile: AgentProfile = BUILTIN_AGENTS[BuiltinAgentName.PLAN]
        middleware = ReadOnlyAgentMiddleware(
            lambda: current_profile,
            BuiltinAgentName.PLAN,
            REMINDER,
            EXIT_MSG,
            sparse_reminder="sparse-msg",
            sparse_every_n_turns=2,
        )

        # Entry
        await middleware.before_turn(ctx)
        # Turn 1 active (no inject)
        r = await middleware.before_turn(ctx)
        assert r.action == MiddlewareAction.CONTINUE
        # Exit before sparse fires
        current_profile = BUILTIN_AGENTS[BuiltinAgentName.DEFAULT]
        r = await middleware.before_turn(ctx)
        assert r.message == EXIT_MSG

        # Re-enter
        current_profile = BUILTIN_AGENTS[BuiltinAgentName.PLAN]
        r = await middleware.before_turn(ctx)
        assert r.message == REMINDER  # full reminder, NOT sparse

    @pytest.mark.asyncio
    async def test_multiple_turns_after_exit(self, ctx: ConversationContext) -> None:
        current_profile: AgentProfile = BUILTIN_AGENTS[BuiltinAgentName.PLAN]
        middleware = _build_middleware(lambda: current_profile)

        await middleware.before_turn(ctx)

        current_profile = BUILTIN_AGENTS[BuiltinAgentName.DEFAULT]
        await middleware.before_turn(ctx)

        for _ in range(5):
            result = await middleware.before_turn(ctx)
            assert result.action == MiddlewareAction.CONTINUE
            assert result.message is None

    @pytest.mark.asyncio
    async def test_rapid_toggling_multiple_cycles(
        self, ctx: ConversationContext
    ) -> None:
        current_profile: AgentProfile = BUILTIN_AGENTS[BuiltinAgentName.PLAN]
        middleware = _build_middleware(lambda: current_profile)

        for _ in range(3):
            current_profile = BUILTIN_AGENTS[BuiltinAgentName.PLAN]
            result = await middleware.before_turn(ctx)
            assert result.action == MiddlewareAction.INJECT_MESSAGE
            assert result.message == REMINDER

            current_profile = BUILTIN_AGENTS[BuiltinAgentName.DEFAULT]
            result = await middleware.before_turn(ctx)
            assert result.action == MiddlewareAction.INJECT_MESSAGE
            assert result.message == EXIT_MSG

    @pytest.mark.asyncio
    async def test_exit_to_non_default_agent(self, ctx: ConversationContext) -> None:
        current_profile: AgentProfile = BUILTIN_AGENTS[BuiltinAgentName.PLAN]
        middleware = _build_middleware(lambda: current_profile)

        await middleware.before_turn(ctx)

        current_profile = BUILTIN_AGENTS[BuiltinAgentName.AUTO_APPROVE]
        result = await middleware.before_turn(ctx)
        assert result.action == MiddlewareAction.INJECT_MESSAGE
        assert result.message == EXIT_MSG

    @pytest.mark.asyncio
    async def test_switching_between_non_target_agents(
        self, ctx: ConversationContext
    ) -> None:
        current_profile: AgentProfile = BUILTIN_AGENTS[BuiltinAgentName.DEFAULT]
        middleware = _build_middleware(lambda: current_profile)

        result = await middleware.before_turn(ctx)
        assert result.action == MiddlewareAction.CONTINUE

        current_profile = BUILTIN_AGENTS[BuiltinAgentName.AUTO_APPROVE]
        result = await middleware.before_turn(ctx)
        assert result.action == MiddlewareAction.CONTINUE

        current_profile = BUILTIN_AGENTS[BuiltinAgentName.ACCEPT_EDITS]
        result = await middleware.before_turn(ctx)
        assert result.action == MiddlewareAction.CONTINUE

    @pytest.mark.asyncio
    async def test_non_target_to_target_entry(self, ctx: ConversationContext) -> None:
        """Starting in a non-target agent then entering target should inject reminder."""
        current_profile: AgentProfile = BUILTIN_AGENTS[BuiltinAgentName.AUTO_APPROVE]
        middleware = _build_middleware(lambda: current_profile)

        result = await middleware.before_turn(ctx)
        assert result.action == MiddlewareAction.CONTINUE

        current_profile = BUILTIN_AGENTS[BuiltinAgentName.PLAN]
        result = await middleware.before_turn(ctx)
        assert result.action == MiddlewareAction.INJECT_MESSAGE
        assert result.message == REMINDER

    @pytest.mark.asyncio
    async def test_reset_while_inactive_after_exit(
        self, ctx: ConversationContext
    ) -> None:
        current_profile: AgentProfile = BUILTIN_AGENTS[BuiltinAgentName.PLAN]
        middleware = _build_middleware(lambda: current_profile)

        await middleware.before_turn(ctx)
        current_profile = BUILTIN_AGENTS[BuiltinAgentName.DEFAULT]
        await middleware.before_turn(ctx)

        middleware.reset()

        result = await middleware.before_turn(ctx)
        assert result.action == MiddlewareAction.CONTINUE

    @pytest.mark.asyncio
    async def test_reset_while_inactive_then_reenter(
        self, ctx: ConversationContext
    ) -> None:
        current_profile: AgentProfile = BUILTIN_AGENTS[BuiltinAgentName.PLAN]
        middleware = _build_middleware(lambda: current_profile)

        await middleware.before_turn(ctx)
        current_profile = BUILTIN_AGENTS[BuiltinAgentName.DEFAULT]
        await middleware.before_turn(ctx)

        middleware.reset()

        current_profile = BUILTIN_AGENTS[BuiltinAgentName.PLAN]
        result = await middleware.before_turn(ctx)
        assert result.action == MiddlewareAction.INJECT_MESSAGE
        assert result.message == REMINDER

    @pytest.mark.asyncio
    async def test_reset_with_compact_reason(self, ctx: ConversationContext) -> None:
        middleware = _build_middleware(lambda: BUILTIN_AGENTS[BuiltinAgentName.PLAN])
        await middleware.before_turn(ctx)

        middleware.reset(ResetReason.COMPACT)

        result = await middleware.before_turn(ctx)
        assert result.action == MiddlewareAction.INJECT_MESSAGE
        assert result.message == REMINDER

    @pytest.mark.asyncio
    async def test_entry_then_continuation_then_exit_then_continuation(
        self, ctx: ConversationContext
    ) -> None:
        """Each call sees one transition at a time."""
        current_profile: AgentProfile = BUILTIN_AGENTS[BuiltinAgentName.PLAN]
        middleware = _build_middleware(lambda: current_profile)

        result = await middleware.before_turn(ctx)
        assert result.action == MiddlewareAction.INJECT_MESSAGE
        assert result.message == REMINDER

        result = await middleware.before_turn(ctx)
        assert result.action == MiddlewareAction.CONTINUE

        current_profile = BUILTIN_AGENTS[BuiltinAgentName.DEFAULT]
        result = await middleware.before_turn(ctx)
        assert result.action == MiddlewareAction.INJECT_MESSAGE
        assert result.message == EXIT_MSG

        result = await middleware.before_turn(ctx)
        assert result.action == MiddlewareAction.CONTINUE


PLAN_REMINDER_SNIPPET = "Plan mode is active"


class TestMiddlewarePipelineWithReadOnlyAgent:
    @pytest.mark.asyncio
    async def test_pipeline_includes_injection(self, ctx: ConversationContext) -> None:
        plan_reminder = make_plan_agent_reminder("/tmp/test-plan.md")
        pipeline = MiddlewarePipeline()
        pipeline.add(
            ReadOnlyAgentMiddleware(
                lambda: BUILTIN_AGENTS[BuiltinAgentName.PLAN],
                BuiltinAgentName.PLAN,
                plan_reminder,
                PLAN_AGENT_EXIT,
            )
        )

        result = await pipeline.run_before_turn(ctx)

        assert result.action == MiddlewareAction.INJECT_MESSAGE
        assert PLAN_REMINDER_SNIPPET in (result.message or "")

    @pytest.mark.asyncio
    async def test_pipeline_skips_injection_when_not_target_agent(
        self, ctx: ConversationContext
    ) -> None:
        plan_reminder = make_plan_agent_reminder("/tmp/test-plan.md")
        pipeline = MiddlewarePipeline()
        pipeline.add(
            ReadOnlyAgentMiddleware(
                lambda: BUILTIN_AGENTS[BuiltinAgentName.DEFAULT],
                BuiltinAgentName.PLAN,
                plan_reminder,
                PLAN_AGENT_EXIT,
            )
        )

        result = await pipeline.run_before_turn(ctx)

        assert result.action == MiddlewareAction.CONTINUE

    @pytest.mark.asyncio
    async def test_direct_plan_to_chat_transition_delivers_both_messages(
        self, ctx: ConversationContext
    ) -> None:
        plan_reminder = make_plan_agent_reminder("/tmp/test-plan.md")
        current_profile: AgentProfile = BUILTIN_AGENTS[BuiltinAgentName.PLAN]
        pipeline = MiddlewarePipeline()
        pipeline.add(
            ReadOnlyAgentMiddleware(
                lambda: current_profile,
                BuiltinAgentName.PLAN,
                plan_reminder,
                PLAN_AGENT_EXIT,
            )
        )
        pipeline.add(
            ReadOnlyAgentMiddleware(
                lambda: current_profile,
                BuiltinAgentName.CHAT,
                CHAT_AGENT_REMINDER,
                CHAT_AGENT_EXIT,
            )
        )

        result = await pipeline.run_before_turn(ctx)
        assert result.action == MiddlewareAction.INJECT_MESSAGE
        assert PLAN_REMINDER_SNIPPET in (result.message or "")

        current_profile = CHAT
        result = await pipeline.run_before_turn(ctx)
        assert result.action == MiddlewareAction.INJECT_MESSAGE
        assert PLAN_AGENT_EXIT in (result.message or "")
        assert CHAT_AGENT_REMINDER in (result.message or "")

        current_profile = BUILTIN_AGENTS[BuiltinAgentName.PLAN]
        result = await pipeline.run_before_turn(ctx)
        assert result.action == MiddlewareAction.INJECT_MESSAGE
        assert CHAT_AGENT_EXIT in (result.message or "")
        assert PLAN_REMINDER_SNIPPET in (result.message or "")


def _find_plan_middleware(agent) -> ReadOnlyAgentMiddleware:
    return next(
        mw
        for mw in agent.middleware_pipeline.middlewares
        if isinstance(mw, ReadOnlyAgentMiddleware)
        and mw._agent_name == BuiltinAgentName.PLAN
    )


class TestReadOnlyAgentMiddlewareIntegration:
    @pytest.mark.asyncio
    async def test_switch_agent_preserves_middleware_state_for_exit_message(
        self,
    ) -> None:
        config = build_test_vibe_config(
            system_prompt_id="tests",
            include_project_context=False,
            include_prompt_detail=False,
            include_model_info=False,
            include_commit_signature=False,
            enabled_tools=[],
        )
        agent = build_test_agent_loop(config=config, agent_name=BuiltinAgentName.PLAN)

        plan_middleware = _find_plan_middleware(agent)

        ctx = ConversationContext(
            messages=agent.messages, stats=agent.stats, config=agent.config
        )
        result = await plan_middleware.before_turn(ctx)
        assert result.action == MiddlewareAction.INJECT_MESSAGE
        assert PLAN_REMINDER_SNIPPET in (result.message or "")

        await agent.switch_agent(BuiltinAgentName.DEFAULT)

        plan_middleware_after = _find_plan_middleware(agent)
        assert plan_middleware is plan_middleware_after

        ctx = ConversationContext(
            messages=agent.messages, stats=agent.stats, config=agent.config
        )
        result = await plan_middleware_after.before_turn(ctx)
        assert result.action == MiddlewareAction.INJECT_MESSAGE
        assert result.message == PLAN_AGENT_EXIT

    @pytest.mark.asyncio
    async def test_switch_agent_allows_reinjection_on_reentry(self) -> None:
        config = build_test_vibe_config(
            system_prompt_id="tests",
            include_project_context=False,
            include_prompt_detail=False,
            include_model_info=False,
            include_commit_signature=False,
            enabled_tools=[],
        )
        agent = build_test_agent_loop(config=config, agent_name=BuiltinAgentName.PLAN)

        plan_middleware = _find_plan_middleware(agent)

        ctx = ConversationContext(
            messages=agent.messages, stats=agent.stats, config=agent.config
        )
        await plan_middleware.before_turn(ctx)

        await agent.switch_agent(BuiltinAgentName.DEFAULT)

        ctx = ConversationContext(
            messages=agent.messages, stats=agent.stats, config=agent.config
        )
        result = await plan_middleware.before_turn(ctx)
        assert result.message == PLAN_AGENT_EXIT

        await agent.switch_agent(BuiltinAgentName.PLAN)

        ctx = ConversationContext(
            messages=agent.messages, stats=agent.stats, config=agent.config
        )
        result = await plan_middleware.before_turn(ctx)
        assert result.action == MiddlewareAction.INJECT_MESSAGE
        assert PLAN_REMINDER_SNIPPET in (result.message or "")

    @pytest.mark.asyncio
    async def test_switch_plan_to_auto_approve_fires_exit(self) -> None:
        config = build_test_vibe_config(
            system_prompt_id="tests",
            include_project_context=False,
            include_prompt_detail=False,
            include_model_info=False,
            include_commit_signature=False,
            enabled_tools=[],
        )
        agent = build_test_agent_loop(config=config, agent_name=BuiltinAgentName.PLAN)

        plan_middleware = _find_plan_middleware(agent)

        ctx = ConversationContext(
            messages=agent.messages, stats=agent.stats, config=agent.config
        )
        await plan_middleware.before_turn(ctx)  # enter plan

        await agent.switch_agent(BuiltinAgentName.AUTO_APPROVE)

        ctx = ConversationContext(
            messages=agent.messages, stats=agent.stats, config=agent.config
        )
        result = await plan_middleware.before_turn(ctx)
        assert result.action == MiddlewareAction.INJECT_MESSAGE
        assert result.message == PLAN_AGENT_EXIT

    @pytest.mark.asyncio
    async def test_switch_between_non_plan_agents_no_injection(self) -> None:
        config = build_test_vibe_config(
            system_prompt_id="tests",
            include_project_context=False,
            include_prompt_detail=False,
            include_model_info=False,
            include_commit_signature=False,
            enabled_tools=[],
        )
        agent = build_test_agent_loop(
            config=config, agent_name=BuiltinAgentName.DEFAULT
        )

        plan_middleware = _find_plan_middleware(agent)

        ctx = ConversationContext(
            messages=agent.messages, stats=agent.stats, config=agent.config
        )
        result = await plan_middleware.before_turn(ctx)
        assert result.action == MiddlewareAction.CONTINUE

        await agent.switch_agent(BuiltinAgentName.AUTO_APPROVE)

        ctx = ConversationContext(
            messages=agent.messages, stats=agent.stats, config=agent.config
        )
        result = await plan_middleware.before_turn(ctx)
        assert result.action == MiddlewareAction.CONTINUE

    @pytest.mark.asyncio
    async def test_full_lifecycle_plan_default_plan_default(self) -> None:
        """Integration test for a full plan -> default -> plan -> default cycle."""
        config = build_test_vibe_config(
            system_prompt_id="tests",
            include_project_context=False,
            include_prompt_detail=False,
            include_model_info=False,
            include_commit_signature=False,
            enabled_tools=[],
        )
        agent = build_test_agent_loop(config=config, agent_name=BuiltinAgentName.PLAN)

        plan_middleware = _find_plan_middleware(agent)

        def _ctx():
            return ConversationContext(
                messages=agent.messages, stats=agent.stats, config=agent.config
            )

        # 1. Enter plan: inject reminder
        r = await plan_middleware.before_turn(_ctx())
        assert r.action == MiddlewareAction.INJECT_MESSAGE
        assert PLAN_REMINDER_SNIPPET in (r.message or "")

        # 2. Stay in plan: no injection
        r = await plan_middleware.before_turn(_ctx())
        assert r.action == MiddlewareAction.CONTINUE

        # 3. Switch to default: inject exit
        await agent.switch_agent(BuiltinAgentName.DEFAULT)
        r = await plan_middleware.before_turn(_ctx())
        assert r.action == MiddlewareAction.INJECT_MESSAGE
        assert r.message == PLAN_AGENT_EXIT

        # 4. Stay in default: no injection
        r = await plan_middleware.before_turn(_ctx())
        assert r.action == MiddlewareAction.CONTINUE

        # 5. Switch back to plan: inject reminder again
        await agent.switch_agent(BuiltinAgentName.PLAN)
        r = await plan_middleware.before_turn(_ctx())
        assert r.action == MiddlewareAction.INJECT_MESSAGE
        assert PLAN_REMINDER_SNIPPET in (r.message or "")

        # 6. Stay in plan: no injection
        r = await plan_middleware.before_turn(_ctx())
        assert r.action == MiddlewareAction.CONTINUE

        # 7. Switch to default again: inject exit
        await agent.switch_agent(BuiltinAgentName.DEFAULT)
        r = await plan_middleware.before_turn(_ctx())
        assert r.action == MiddlewareAction.INJECT_MESSAGE
        assert r.message == PLAN_AGENT_EXIT

        # 8. Stay in default: no injection
        r = await plan_middleware.before_turn(_ctx())
        assert r.action == MiddlewareAction.CONTINUE


class TestMicroCompactMiddleware:
    @pytest.mark.asyncio
    async def test_does_not_trigger_when_threshold_disabled(self) -> None:
        """When the active model has auto_compact_threshold <= 0 (compaction
        disabled), MicroCompactMiddleware MUST short-circuit even at huge
        context_tokens. Without this guard the inner ratio math collapses
        (target_water=0, micro_threshold=0) and the function would clear
        every eligible result. The /compact --micro UI command relies on
        this same contract.
        """
        cfg = build_test_vibe_config()
        cfg.get_active_model().auto_compact_threshold = 0
        messages = MessageList([
            LLMMessage(
                role=Role.tool, name="bash", tool_call_id="c1", content="X" * 100_000
            )
        ])
        stats = AgentStats()
        stats.context_tokens = 999_999  # absurdly large; guard MUST still fire
        ctx = ConversationContext(messages=messages, stats=stats, config=cfg)
        mw = MicroCompactMiddleware()

        result = await mw.before_turn(ctx)

        assert result.action == MiddlewareAction.CONTINUE
        assert stats.cleared_tool_results == 0
        assert messages[0].content == "X" * 100_000

    @pytest.mark.asyncio
    async def test_does_not_trigger_below_threshold(self) -> None:
        cfg = build_test_vibe_config()
        messages = MessageList([
            LLMMessage(
                role=Role.tool, name="bash", tool_call_id="c1", content="A" * 1000
            )
        ])
        stats = AgentStats()
        stats.context_tokens = 100  # well below 200_000 * 0.7 = 140_000
        ctx = ConversationContext(messages=messages, stats=stats, config=cfg)
        mw = MicroCompactMiddleware()

        result = await mw.before_turn(ctx)

        assert result.action == MiddlewareAction.CONTINUE
        assert stats.cleared_tool_results == 0
        assert messages[0].content == "A" * 1000

    @pytest.mark.asyncio
    async def test_clears_results_when_above_threshold(self) -> None:
        cfg = build_test_vibe_config()
        big_content = "B" * 600_000  # ~150_000 tokens
        # Three bash results: default micro_keep_last=2 protects the latter
        # two; the oldest (index 0, big) is the only candidate.
        messages = MessageList([
            LLMMessage(
                role=Role.tool, name="bash", tool_call_id="c1", content=big_content
            ),
            LLMMessage(
                role=Role.tool, name="bash", tool_call_id="c2", content="recent1"
            ),
            LLMMessage(
                role=Role.tool, name="bash", tool_call_id="c3", content="recent2"
            ),
        ])
        stats = AgentStats()
        stats.context_tokens = 150_000  # above 200_000 * 0.7 = 140_000
        ctx = ConversationContext(messages=messages, stats=stats, config=cfg)
        mw = MicroCompactMiddleware()

        result = await mw.before_turn(ctx)

        assert result.action == MiddlewareAction.CONTINUE
        assert "[Old tool result cleared" in (messages[0].content or "")
        assert messages[1].content == "recent1"
        assert messages[2].content == "recent2"
        assert stats.cleared_tool_results >= 1

    @pytest.mark.asyncio
    async def test_micro_runs_before_auto_compact_in_pipeline(self) -> None:
        """Ordering property: when registered before AutoCompact, MicroCompact
        clears old tool results first and lowers ``context_tokens`` so the
        subsequent AutoCompact sees a value below threshold and does NOT fire.

        Critical: ``context_tokens`` must START above the auto-compact
        threshold (200_000), otherwise AutoCompact would never have fired
        anyway and the test would pass even with broken ordering. The
        previous version of this test used 150_000 — below threshold — so
        it was vacuously correct.
        """
        from vibe.core.middleware import AutoCompactMiddleware

        cfg = build_test_vibe_config()
        big_content = (
            "C" * 600_000
        )  # ~150_000 tokens — enough headroom to drop below 200_000

        def _build_ctx() -> ConversationContext:
            messages = MessageList([
                LLMMessage(
                    role=Role.tool, name="bash", tool_call_id="c1", content=big_content
                ),
                LLMMessage(
                    role=Role.tool, name="bash", tool_call_id="c2", content="recent1"
                ),
                LLMMessage(
                    role=Role.tool, name="bash", tool_call_id="c3", content="recent2"
                ),
            ])
            stats = AgentStats()
            stats.context_tokens = 210_000  # ABOVE auto-compact threshold (200_000)
            return ConversationContext(messages=messages, stats=stats, config=cfg)

        # Negative control: AutoCompact alone at 210k DOES fire. This proves
        # the threshold setup is real — without it, the assertion below
        # could not distinguish "micro saved us" from "Auto never fires here".
        ctx_auto_only = _build_ctx()
        auto_only = MiddlewarePipeline()
        auto_only.add(AutoCompactMiddleware())
        auto_result = await auto_only.run_before_turn(ctx_auto_only)
        assert auto_result.action == MiddlewareAction.COMPACT, (
            "Negative control failed — AutoCompact didn't fire at 210k tokens, "
            "so the positive assertion below would be vacuous."
        )

        # Positive: with MicroCompact registered first, it reclaims tokens
        # and AutoCompact (running after) stays CONTINUE.
        ctx = _build_ctx()
        pipeline = MiddlewarePipeline()
        pipeline.add(MicroCompactMiddleware())
        pipeline.add(AutoCompactMiddleware())
        result = await pipeline.run_before_turn(ctx)

        assert result.action == MiddlewareAction.CONTINUE
        assert (
            ctx.stats.context_tokens < 200_000
        )  # micro brought us below the threshold
        assert ctx.stats.cleared_tool_results >= 1

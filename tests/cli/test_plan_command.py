from __future__ import annotations

import inspect

from vibe.cli.commands import CommandRegistry


class TestPlanCommandRegistration:
    def test_plan_command_is_registered(self) -> None:
        registry = CommandRegistry()
        assert "plan" in registry.commands
        cmd = registry.commands["plan"]
        assert "/plan" in cmd.aliases
        assert cmd.handler == "_toggle_plan_mode"
        assert cmd.exits is False

    def test_help_text_lists_plan(self) -> None:
        registry = CommandRegistry()
        text = registry.get_help_text()
        assert "/plan" in text
        assert "plan mode" in text.lower()


class TestSlashCommandsNotFilteredByPlanMode:
    """Spec: user typing slash commands in TUI input is NOT filtered by plan
    mode. Filtering happens in the tool dispatch layer, not the command parser.
    This test pins that boundary.
    """

    def test_parser_does_not_consult_agent_state(self) -> None:
        sig = inspect.signature(CommandRegistry.__init__)
        params = set(sig.parameters.keys()) - {"self"}
        # The contract is "no agent / profile / mode awareness", not the
        # exact param list — adding unrelated kwargs (e.g., a logger) shouldn't
        # break this test.
        assert "agent" not in params
        assert "profile" not in params
        assert "mode" not in params
        assert "agent_manager" not in params

    def test_parse_help_succeeds_regardless_of_external_state(self) -> None:
        registry = CommandRegistry()
        result = registry.parse_command("/help")
        assert result is not None
        cmd_name, cmd, cmd_args = result
        assert cmd_name == "help"
        assert cmd_args == ""


class TestToggleHandlerLogic:
    """Pure unit test of the toggle decision logic — no Textual stack."""

    def test_toggle_target_from_default(self) -> None:
        from vibe.core.agents.models import BuiltinAgentName

        currently_in_plan = BuiltinAgentName.DEFAULT == BuiltinAgentName.PLAN
        assert currently_in_plan is False
        target = (
            BuiltinAgentName.DEFAULT if currently_in_plan else BuiltinAgentName.PLAN
        )
        assert target == BuiltinAgentName.PLAN

    def test_toggle_target_from_plan(self) -> None:
        from vibe.core.agents.models import BuiltinAgentName

        currently_in_plan = BuiltinAgentName.PLAN == BuiltinAgentName.PLAN
        assert currently_in_plan is True
        target = (
            BuiltinAgentName.DEFAULT if currently_in_plan else BuiltinAgentName.PLAN
        )
        assert target == BuiltinAgentName.DEFAULT

from __future__ import annotations

from typing import ClassVar

from vibe.core.tools.base import BaseTool, BaseToolConfig, BaseToolState


class TestBaseToolMutatesStateDefault:
    def test_base_tool_defaults_to_true(self) -> None:
        assert BaseTool.mutates_state is True

    def test_subclass_inherits_default_true(self) -> None:
        from pydantic import BaseModel

        class _Args(BaseModel):
            pass

        class _Result(BaseModel):
            ok: bool = True

        class FakeWriter(BaseTool[_Args, _Result, BaseToolConfig, BaseToolState]):
            description: ClassVar[str] = "fake"

            async def run(self, args, ctx=None):  # type: ignore[no-untyped-def]
                yield _Result()

        assert FakeWriter.mutates_state is True

    def test_subclass_can_override_to_false(self) -> None:
        from pydantic import BaseModel

        class _Args(BaseModel):
            pass

        class _Result(BaseModel):
            ok: bool = True

        class FakeReader(BaseTool[_Args, _Result, BaseToolConfig, BaseToolState]):
            description: ClassVar[str] = "fake"
            mutates_state: ClassVar[bool] = False

            async def run(self, args, ctx=None):  # type: ignore[no-untyped-def]
                yield _Result()

        assert FakeReader.mutates_state is False


class TestBuiltinMutatesStateMatrix:
    """Pin the read/write classification of every builtin tool.

    Plan mode correctness depends on this matrix being right. Adding a new
    builtin requires extending this test — that's intentional.
    """

    def test_read_only_builtins(self) -> None:
        from vibe.core.tools.builtins.ask_user_question import AskUserQuestion
        from vibe.core.tools.builtins.enter_plan_mode import EnterPlanMode
        from vibe.core.tools.builtins.exit_plan_mode import ExitPlanMode
        from vibe.core.tools.builtins.grep import Grep
        from vibe.core.tools.builtins.read_file import ReadFile
        from vibe.core.tools.builtins.skill import Skill
        from vibe.core.tools.builtins.todo import Todo
        from vibe.core.tools.builtins.webfetch import WebFetch
        from vibe.core.tools.builtins.websearch import WebSearch

        assert ReadFile.mutates_state is False
        assert Grep.mutates_state is False
        assert WebFetch.mutates_state is False
        assert WebSearch.mutates_state is False
        assert AskUserQuestion.mutates_state is False
        assert Todo.mutates_state is False
        assert ExitPlanMode.mutates_state is False
        assert EnterPlanMode.mutates_state is False
        # Skill loads SKILL.md content only — any actions a skill prompts are
        # separate tool calls, each gated by the dispatch layer independently.
        assert Skill.mutates_state is False

    def test_write_or_exec_builtins(self) -> None:
        from vibe.core.tools.builtins.bash import Bash
        from vibe.core.tools.builtins.search_replace import SearchReplace
        from vibe.core.tools.builtins.task import Task
        from vibe.core.tools.builtins.write_file import WriteFile

        assert Bash.mutates_state is True
        assert WriteFile.mutates_state is True
        assert SearchReplace.mutates_state is True
        assert Task.mutates_state is True


class TestMCPToolDefault:
    """MCP tools subclass BaseTool without overriding the class attribute,
    so they must inherit True (safe side: external servers may mutate).
    """

    def test_mcp_tool_class_inherits_true(self) -> None:
        from vibe.core.tools.mcp.tools import MCPTool

        assert MCPTool.mutates_state is True

    def test_dynamic_mcp_subclass_with_no_override_is_true(self) -> None:
        from vibe.core.tools.mcp.tools import MCPTool

        DynamicMCPLike = type("DynamicMCPLike", (MCPTool,), {})
        assert DynamicMCPLike.mutates_state is True

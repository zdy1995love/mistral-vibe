from __future__ import annotations

from vibe.core.agent_loop import _promote_inline_tool_calls
from vibe.core.types import LLMMessage, Role


def _msg(content: str | None, *, tool_calls: list | None = None) -> LLMMessage:
    return LLMMessage(role=Role.assistant, content=content, tool_calls=tool_calls)


class TestPromoteInlineToolCalls:
    """Recover when the model emits a tool call as bare ``<name>{<json>}``
    text at content's tail instead of the proper ``[TOOL_CALLS]<name>{...}``
    structure (a known Mistral-style token-level glitch under
    reasoning_effort=high in long contexts).
    """

    def test_promotes_inline_call_at_content_tail(self) -> None:
        msg = _msg(
            'Plan summary text.\n\nwrite_file{"path": "/tmp/x.md", "content": "# Hi"}'
        )
        out = _promote_inline_tool_calls(msg, {"write_file"})
        assert out.tool_calls is not None and len(out.tool_calls) == 1
        tc = out.tool_calls[0]
        assert tc.function.name == "write_file"
        assert tc.function.arguments == '{"path": "/tmp/x.md", "content": "# Hi"}'
        assert out.content == "Plan summary text."

    def test_strips_trailing_whitespace_from_remaining_content(self) -> None:
        msg = _msg('Body.\n\nwrite_file{"path": "x"}\n  ')
        out = _promote_inline_tool_calls(msg, {"write_file"})
        assert out.content == "Body."

    def test_no_remaining_content_becomes_none(self) -> None:
        msg = _msg('write_file{"path": "x"}')
        out = _promote_inline_tool_calls(msg, {"write_file"})
        assert out.content is None
        assert out.tool_calls and out.tool_calls[0].function.name == "write_file"

    def test_existing_structured_tool_calls_short_circuit(self) -> None:
        # If real tool_calls are already present, don't second-guess.
        from vibe.core.types import FunctionCall, ToolCall

        existing = [ToolCall(id="abc", index=0, function=FunctionCall(name="real", arguments="{}"))]
        msg = _msg('text write_file{"path": "x"}', tool_calls=existing)
        out = _promote_inline_tool_calls(msg, {"write_file"})
        assert out is msg  # short-circuit returns the original message unchanged
        assert out.tool_calls is not None and len(out.tool_calls) == 1
        assert out.tool_calls[0].function.name == "real"
        assert out.content == 'text write_file{"path": "x"}'

    def test_unknown_tool_name_not_promoted(self) -> None:
        msg = _msg('text mystery_tool{"x": 1}')
        out = _promote_inline_tool_calls(msg, {"write_file", "read_file"})
        assert out.tool_calls is None
        assert out.content == 'text mystery_tool{"x": 1}'

    def test_inline_text_not_at_tail_not_promoted(self) -> None:
        msg = _msg('write_file{"path": "x"} and then more text after the tool call.')
        out = _promote_inline_tool_calls(msg, {"write_file"})
        assert out.tool_calls is None
        assert out.content == 'write_file{"path": "x"} and then more text after the tool call.'

    def test_invalid_json_not_promoted(self) -> None:
        msg = _msg('text write_file{"path": "x"')  # missing closing brace
        out = _promote_inline_tool_calls(msg, {"write_file"})
        assert out.tool_calls is None

    def test_json_array_not_promoted(self) -> None:
        # Only object-shaped JSON counts as a tool-call argument body.
        msg = _msg('text write_file[1, 2, 3]')
        out = _promote_inline_tool_calls(msg, {"write_file"})
        assert out.tool_calls is None

    def test_name_part_of_longer_identifier_not_promoted(self) -> None:
        # 'my_write_file' contains 'write_file' but the boundary check
        # rejects it: the char before 'write_file' is '_'.
        msg = _msg('text my_write_file{"x": 1}')
        out = _promote_inline_tool_calls(msg, {"write_file"})
        assert out.tool_calls is None

    def test_longer_name_preferred_over_shorter(self) -> None:
        # If both 'write' and 'write_file' are available, prefer longer.
        msg = _msg('text write_file{"path": "x"}')
        out = _promote_inline_tool_calls(msg, {"write", "write_file"})
        assert out.tool_calls and out.tool_calls[0].function.name == "write_file"

    def test_empty_content_returns_message_unchanged(self) -> None:
        msg = _msg(None)
        out = _promote_inline_tool_calls(msg, {"write_file"})
        assert out is msg

    def test_no_available_tools_returns_message_unchanged(self) -> None:
        msg = _msg('text write_file{"path": "x"}')
        out = _promote_inline_tool_calls(msg, set())
        assert out is msg

    def test_real_user_session_pattern(self) -> None:
        """The exact pattern from session_20260507_045823: the orphan
        [/THINK] gets handled by ThinkTagExtractor (not this helper);
        downstream content arrives as <visible_reply>write_file{<json>}.
        """
        content = (
            "根据对比文档，**vibe 还需要开发的功能**按优先级分为三个梯队：\n\n"
            "**第一梯队（必做）**：\n"
            "- Microcompact（压缩算法）\n"
            "- **Hooks 系统**\n"
            "- 后台 fork 子 agent 基建\n\n"
            'write_file{"path": "/home/zdy/.vibe/plans/1778129923-clever-cool-dawn.md", '
            '"content": "# Hooks 系统开发计划\\n\\n## 目标\\n实现类似 Claude Code"}'
        )
        msg = _msg(content)
        out = _promote_inline_tool_calls(msg, {"write_file", "read_file", "bash"})
        assert out.tool_calls is not None
        assert out.tool_calls[0].function.name == "write_file"
        assert "/home/zdy/.vibe/plans" in out.tool_calls[0].function.arguments
        assert out.content is not None and "Microcompact" in out.content
        assert "write_file{" not in out.content

"""Unit coverage for the tool_call.arguments sanitizer in agent_loop.

Streaming truncation can leave a tool_call's `arguments` string as
malformed JSON. The sanitizer rewrites such fragments to `{}` before the
assistant message is appended to history — without it, vLLM rejects the
next-turn request with `Unterminated string starting at: line 1 column 13`
because vLLM validates each tool_call's arguments as standalone JSON.
"""

from __future__ import annotations

from vibe.core.agent_loop import _sanitize_tool_call_arguments
from vibe.core.types import FunctionCall, LLMMessage, Role, ToolCall


def _make_message_with_args(arguments: str) -> LLMMessage:
    return LLMMessage(
        role=Role.assistant,
        content=None,
        tool_calls=[
            ToolCall(
                id="abc",
                index=0,
                type="function",
                function=FunctionCall(name="bash", arguments=arguments),
            )
        ],
    )


class TestSanitizeToolCallArguments:
    def test_passes_through_valid_json(self) -> None:
        msg = _make_message_with_args('{"command": "ls"}')
        out = _sanitize_tool_call_arguments(msg)
        assert out is msg, "valid JSON should round-trip without copy"
        assert out.tool_calls is not None
        assert out.tool_calls[0].function.arguments == '{"command": "ls"}'

    def test_passes_through_empty_object(self) -> None:
        msg = _make_message_with_args("{}")
        out = _sanitize_tool_call_arguments(msg)
        assert out is msg
        assert out.tool_calls is not None
        assert out.tool_calls[0].function.arguments == "{}"

    def test_rewrites_truncated_string_args(self) -> None:
        # The actual failure mode the user hit: stream cut off mid-string.
        msg = _make_message_with_args('{"command": "ls -la /home/zdy/zeroclaw')
        out = _sanitize_tool_call_arguments(msg)
        assert out is not msg, "broken args should produce a new message"
        assert out.tool_calls is not None
        assert out.tool_calls[0].function.arguments == "{}"
        # Identity preserved so the model still sees a well-formed tool call.
        assert out.tool_calls[0].id == "abc"
        assert out.tool_calls[0].function.name == "bash"

    def test_rewrites_open_brace_only(self) -> None:
        msg = _make_message_with_args("{")
        out = _sanitize_tool_call_arguments(msg)
        assert out.tool_calls is not None
        assert out.tool_calls[0].function.arguments == "{}"

    def test_rewrites_garbage_args(self) -> None:
        msg = _make_message_with_args("not even close to json")
        out = _sanitize_tool_call_arguments(msg)
        assert out.tool_calls is not None
        assert out.tool_calls[0].function.arguments == "{}"

    def test_no_op_when_no_tool_calls(self) -> None:
        msg = LLMMessage(role=Role.assistant, content="just text")
        out = _sanitize_tool_call_arguments(msg)
        assert out is msg

    def test_no_op_when_arguments_is_none(self) -> None:
        msg = LLMMessage(
            role=Role.assistant,
            content=None,
            tool_calls=[
                ToolCall(
                    id="x",
                    index=0,
                    type="function",
                    function=FunctionCall(name="bash", arguments=None),
                )
            ],
        )
        out = _sanitize_tool_call_arguments(msg)
        assert out is msg

    def test_partial_repair_when_mixed_valid_and_broken(self) -> None:
        msg = LLMMessage(
            role=Role.assistant,
            content=None,
            tool_calls=[
                ToolCall(
                    id="ok",
                    index=0,
                    type="function",
                    function=FunctionCall(name="bash", arguments='{"command": "ls"}'),
                ),
                ToolCall(
                    id="broken",
                    index=1,
                    type="function",
                    function=FunctionCall(name="bash", arguments='{"command": "rm'),
                ),
            ],
        )
        out = _sanitize_tool_call_arguments(msg)
        assert out is not msg
        assert out.tool_calls is not None
        assert out.tool_calls[0].function.arguments == '{"command": "ls"}'
        assert out.tool_calls[1].function.arguments == "{}"

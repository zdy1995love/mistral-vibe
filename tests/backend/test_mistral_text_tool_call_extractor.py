from __future__ import annotations

import json

import pytest

from vibe.core.llm.backend.mistral_text_tool_call_extractor import (
    MistralToolCallTextExtractor,
)


def _replay(chunks: list[str]) -> tuple[str, list[tuple[str, str, int]]]:
    """Feed chunks through extractor and return (full_content, [(name, args, index), ...])."""
    ex = MistralToolCallTextExtractor()
    content = ""
    calls: list[tuple[str, str, int]] = []
    for c in chunks:
        cont, completed = ex.feed(c)
        content += cont
        for tc in completed:
            calls.append((tc.name, tc.arguments, tc.index))
    tail_c, tail_calls = ex.flush()
    content += tail_c
    for tc in tail_calls:
        calls.append((tc.name, tc.arguments, tc.index))
    return content, calls


# --- pass-through ---


def test_plain_text_passes_through_untouched() -> None:
    content, calls = _replay(["hello ", "world", "!"])
    assert content == "hello world!"
    assert calls == []


def test_empty_feed_is_noop() -> None:
    ex = MistralToolCallTextExtractor()
    assert ex.feed("") == ("", [])
    assert ex.flush() == ("", [])


# --- happy-path tool-call recovery ---


def test_extracts_single_tool_call_split_across_many_chunks() -> None:
    chunks = [
        "[TOOL_CALLS]",
        "bash",
        '{"',
        "command",
        '":',
        ' "',
        "ls",
        ' -la"',
        "}",
    ]
    content, calls = _replay(chunks)
    assert content == ""
    assert len(calls) == 1
    name, args, index = calls[0]
    assert name == "bash"
    assert json.loads(args) == {"command": "ls -la"}
    assert index == 0


def test_extracts_two_back_to_back_tool_calls_with_increasing_index() -> None:
    chunks = ['[TOOL_CALLS]bash{"command":"ls"}[TOOL_CALLS]read_file{"path":"a.py"}']
    content, calls = _replay(chunks)
    assert content == ""
    assert calls == [
        ("bash", '{"command":"ls"}', 0),
        ("read_file", '{"path":"a.py"}', 1),
    ]


def test_handles_nested_json_with_string_braces() -> None:
    chunks = ['[TOOL_CALLS]complex{"nested":{"a":1,"b":[2,3]},"str":"with } brace"}']
    content, calls = _replay(chunks)
    assert content == ""
    assert len(calls) == 1
    assert calls[0][0] == "complex"
    assert json.loads(calls[0][1]) == {
        "nested": {"a": 1, "b": [2, 3]},
        "str": "with } brace",
    }


def test_strips_args_separator_token_in_name() -> None:
    """Mistral v11 wire format may include `[ARGS]` between name and args."""
    chunks = ['[TOOL_CALLS]bash[ARGS]{"command":"ls"}']
    content, calls = _replay(chunks)
    assert content == ""
    assert calls == [("bash", '{"command":"ls"}', 0)]


def test_pre_tool_call_content_emitted_as_content() -> None:
    chunks = ["Let me ", "use bash. ", "[TOO", "L_CALLS]", 'bash{"command":"ls"}']
    content, calls = _replay(chunks)
    assert content == "Let me use bash. "
    assert len(calls) == 1


def test_partial_marker_at_chunk_boundary_buffered() -> None:
    """If a chunk ends with `[T`, parser holds back to see if it completes `[TOOL_CALLS]`."""
    chunks = ["text and then [T", 'OOL_CALLS]bash{"command":"ls"}']
    content, calls = _replay(chunks)
    assert content == "text and then "
    assert len(calls) == 1


# --- false-positive rejection (regression: vibe got 400 from server when
#     dispatching synthetic call with non-JSON args) ---


def test_rejects_placeholder_name_and_invalid_args_keeps_content() -> None:
    """User asked the model about format; response had literal example text."""
    chunks = ["调用工具用 [TOOL_CALLS]<name>{<args>} 这种格式"]
    content, calls = _replay(chunks)
    assert calls == []
    assert "[TOOL_CALLS]<name>{<args>}" in content


def test_rejects_name_with_angle_brackets_even_if_args_valid_json() -> None:
    chunks = ["[TOOL_CALLS]<x>{}"]
    content, calls = _replay(chunks)
    assert calls == []
    assert content == "[TOOL_CALLS]<x>{}"


def test_rejects_name_with_space() -> None:
    chunks = ['[TOOL_CALLS]some thing{"a":1} after']
    content, calls = _replay(chunks)
    assert calls == []
    assert "[TOOL_CALLS]some thing" in content


def test_rejects_invalid_json_args() -> None:
    chunks = ["[TOOL_CALLS]bash{not_json}"]
    content, calls = _replay(chunks)
    assert calls == []
    assert content == "[TOOL_CALLS]bash{not_json}"


def test_real_tool_call_after_false_positive_in_same_stream() -> None:
    chunks = [
        "解释格式 [TOOL_CALLS]<name>{<args>}。",
        '现在真的调一下：[TOOL_CALLS]bash{"command":"ls"}',
    ]
    content, calls = _replay(chunks)
    assert "[TOOL_CALLS]<name>{<args>}" in content
    assert calls == [("bash", '{"command":"ls"}', 0)]


def test_rejects_oversized_name_without_brace() -> None:
    """Safety against unbounded buffering when [TOOL_CALLS] never closes properly."""
    chunks = ["[TOOL_CALLS]" + "x" * 300 + '{"a":1}']
    content, calls = _replay(chunks)
    assert calls == []
    assert content.startswith("[TOOL_CALLS]xxx")


# --- flush behavior ---


def test_flush_drops_incomplete_args() -> None:
    """If stream ends mid-args (no closing brace), tool call is unrecoverable."""
    ex = MistralToolCallTextExtractor()
    ex.feed('[TOOL_CALLS]bash{"command":"ls')
    tail_c, tail_calls = ex.flush()
    assert tail_calls == []
    assert tail_c == ""


def test_flush_re_emits_dangling_marker_text_as_content() -> None:
    """`[TOOL_CALLS]name` with no `{` ever — re-emit as content at flush."""
    ex = MistralToolCallTextExtractor()
    ex.feed("[TOOL_CALLS]bash without args")
    tail_c, tail_calls = ex.flush()
    assert tail_calls == []
    assert tail_c == "[TOOL_CALLS]bash without args"


def test_flush_emits_pending_partial_suffix() -> None:
    """Trailing `[TOO` partial-suffix cache — emit verbatim at flush."""
    ex = MistralToolCallTextExtractor()
    cont, _ = ex.feed("just text [TOO")
    assert cont == "just text "
    tail_c, tail_calls = ex.flush()
    assert tail_calls == []
    assert tail_c == "[TOO"


# --- guard predicate ---


@pytest.mark.parametrize(
    "name,args,expected",
    [
        ("bash", "{}", True),
        ("read_file", '{"path":"a"}', True),
        ("Foo_Bar-baz", '{"x":1}', True),
        ("9digit", "{}", False),  # cannot start with digit
        ("", "{}", False),
        ("<name>", "{}", False),  # angle brackets
        ("name with space", "{}", False),
        ("a" * 200, "{}", False),  # too long
        ("bash", "{not_json}", False),
        ("bash", "", False),
        ("bash", "[1,2,3]", True),  # JSON arrays are also valid
    ],
)
def test_is_valid_tool_call_predicate(name: str, args: str, expected: bool) -> None:
    assert (
        MistralToolCallTextExtractor._is_valid_tool_call(name, args) is expected
    )

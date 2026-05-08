from __future__ import annotations

from vibe.core.llm.backend.generic import _apply_think_extractor_oneshot
from vibe.core.llm.types import LLMChunk
from vibe.core.types import LLMMessage, LLMUsage, Role


def _chunk(content: str | None, reasoning: str | None = None) -> LLMChunk:
    return LLMChunk(
        message=LLMMessage(
            role=Role.assistant,
            content=content,
            reasoning_content=reasoning,
        ),
        usage=LLMUsage(prompt_tokens=10, completion_tokens=5, cached_prompt_tokens=0),
    )


def test_oneshot_extracts_paired_think_block() -> None:
    out = _apply_think_extractor_oneshot(_chunk("[THINK]reason[/THINK]answer"))
    assert out.message.content == "answer"
    assert out.message.reasoning_content == "reason"


def test_oneshot_passthrough_when_no_tags() -> None:
    out = _apply_think_extractor_oneshot(_chunk("plain answer"))
    assert out.message.content == "plain answer"
    assert out.message.reasoning_content is None


def test_oneshot_passthrough_when_reasoning_already_set() -> None:
    out = _apply_think_extractor_oneshot(
        _chunk("[THINK]should not run[/THINK]answer", reasoning="already parsed")
    )
    assert out.message.content == "[THINK]should not run[/THINK]answer"
    assert out.message.reasoning_content == "already parsed"


def test_oneshot_strips_orphan_close_tag() -> None:
    """Mistral-style orphan [/THINK] (no preceding [THINK]) must be swallowed
    in the non-streaming path, matching the streaming path's behavior. The
    earlier guard `'[THINK]' not in content` short-circuited because
    '[THINK]' is not a substring of '[/THINK]' — the tag leaked through
    verbatim."""
    out = _apply_think_extractor_oneshot(_chunk("answer [/THINK]"))
    assert out.message.content == "answer "
    assert out.message.reasoning_content is None


def test_oneshot_strips_orphan_close_tag_in_middle() -> None:
    out = _apply_think_extractor_oneshot(_chunk("hello[/THINK]world"))
    assert out.message.content == "helloworld"
    assert out.message.reasoning_content is None

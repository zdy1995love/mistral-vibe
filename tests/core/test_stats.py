from __future__ import annotations

from vibe.core.types import LLMUsage


def test_llm_usage_cached_default_zero() -> None:
    u = LLMUsage(prompt_tokens=100, completion_tokens=10)
    assert u.cached_prompt_tokens == 0


def test_llm_usage_add_accumulates_cached() -> None:
    a = LLMUsage(prompt_tokens=200, completion_tokens=5, cached_prompt_tokens=180)
    b = LLMUsage(prompt_tokens=300, completion_tokens=8, cached_prompt_tokens=290)
    c = a + b
    assert c.prompt_tokens == 500
    assert c.completion_tokens == 13
    assert c.cached_prompt_tokens == 470

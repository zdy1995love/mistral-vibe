from __future__ import annotations

from vibe.core.llm.backend.generic import OpenAIAdapter
from vibe.core.config._settings import ProviderConfig
from vibe.core.types import Backend


def _provider() -> ProviderConfig:
    return ProviderConfig(
        name="test",
        api_base="http://localhost:0",
        api_key_env_var="",
        backend=Backend.GENERIC,
    )


def test_generic_extracts_cached_tokens_from_prompt_tokens_details() -> None:
    adapter = OpenAIAdapter()
    data = {
        "choices": [{"delta": {"role": "assistant", "content": "hi"}}],
        "usage": {
            "prompt_tokens": 2021,
            "completion_tokens": 2,
            "prompt_tokens_details": {"cached_tokens": 2016},
        },
    }
    chunk = adapter.parse_response(data, _provider())
    assert chunk.usage is not None
    assert chunk.usage.prompt_tokens == 2021
    assert chunk.usage.completion_tokens == 2
    assert chunk.usage.cached_prompt_tokens == 2016


def test_generic_cached_tokens_missing_defaults_to_zero() -> None:
    adapter = OpenAIAdapter()
    data = {
        "choices": [{"delta": {"role": "assistant", "content": "hi"}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 5},
    }
    chunk = adapter.parse_response(data, _provider())
    assert chunk.usage is not None
    assert chunk.usage.cached_prompt_tokens == 0


def test_generic_prompt_tokens_details_null_defaults_to_zero() -> None:
    """vLLM's first call returns prompt_tokens_details: null."""
    adapter = OpenAIAdapter()
    data = {
        "choices": [{"delta": {"role": "assistant", "content": "hi"}}],
        "usage": {
            "prompt_tokens": 2021,
            "completion_tokens": 2,
            "prompt_tokens_details": None,
        },
    }
    chunk = adapter.parse_response(data, _provider())
    assert chunk.usage is not None
    assert chunk.usage.cached_prompt_tokens == 0

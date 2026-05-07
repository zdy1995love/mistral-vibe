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


def test_anthropic_maps_cache_read_to_cached_prompt_tokens() -> None:
    """cache_read counts as a cache hit; cache_creation does not."""
    from vibe.core.llm.backend.anthropic import _build_usage_from_message_response

    data = {
        "usage": {
            "input_tokens": 50,
            "cache_creation_input_tokens": 200,
            "cache_read_input_tokens": 1800,
            "output_tokens": 30,
        },
    }
    usage = _build_usage_from_message_response(data)
    assert usage.prompt_tokens == 50 + 200 + 1800
    assert usage.completion_tokens == 30
    assert usage.cached_prompt_tokens == 1800  # cache_read only


def test_anthropic_cache_fields_missing_defaults_to_zero() -> None:
    from vibe.core.llm.backend.anthropic import _build_usage_from_message_response

    data = {"usage": {"input_tokens": 100, "output_tokens": 5}}
    usage = _build_usage_from_message_response(data)
    assert usage.prompt_tokens == 100
    assert usage.cached_prompt_tokens == 0


def test_openai_responses_extracts_cached_tokens() -> None:
    from vibe.core.llm.backend.openai_responses import _build_usage

    usage = _build_usage({
        "input_tokens": 1000,
        "output_tokens": 20,
        "input_tokens_details": {"cached_tokens": 850},
    })
    assert usage.prompt_tokens == 1000
    assert usage.completion_tokens == 20
    assert usage.cached_prompt_tokens == 850


def test_openai_responses_missing_details_defaults_to_zero() -> None:
    from vibe.core.llm.backend.openai_responses import _build_usage

    usage = _build_usage({"input_tokens": 100, "output_tokens": 5})
    assert usage.cached_prompt_tokens == 0

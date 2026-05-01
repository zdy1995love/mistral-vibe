from __future__ import annotations

from unittest.mock import MagicMock

from mcp.types import (
    CreateMessageRequestParams,
    CreateMessageResult,
    SamplingMessage,
    TextContent,
)
import pytest

from tests.conftest import (
    build_test_agent_loop,
    build_test_vibe_config,
    make_test_models,
)
from tests.mock.utils import mock_llm_chunk
from tests.stubs.fake_backend import FakeBackend
from vibe.core.agents.models import BuiltinAgentName
from vibe.core.config import ModelConfig, ProviderConfig, VibeConfig
from vibe.core.telemetry.types import EntrypointMetadata
from vibe.core.tools.base import BaseToolConfig, ToolPermission
from vibe.core.types import Backend, FunctionCall, Role, ToolCall


def _two_model_vibe_config(active_model: str) -> VibeConfig:
    """VibeConfig with two models so we can switch active_model."""
    models = [
        ModelConfig(
            name="mistral-vibe-cli-latest", provider="mistral", alias="devstral-latest"
        ),
        ModelConfig(
            name="devstral-small-latest", provider="mistral", alias="devstral-small"
        ),
    ]
    providers = [
        ProviderConfig(
            name="mistral",
            api_base="https://api.mistral.ai/v1",
            api_key_env_var="MISTRAL_API_KEY",
            backend=Backend.MISTRAL,
        )
    ]
    return build_test_vibe_config(
        active_model=active_model, models=models, providers=providers
    )


def _make_sampling_params() -> CreateMessageRequestParams:
    return CreateMessageRequestParams(
        messages=[
            SamplingMessage(role="user", content=TextContent(type="text", text="Hi"))
        ],
        systemPrompt=None,
        temperature=None,
        maxTokens=100,
    )


@pytest.mark.asyncio
async def test_passes_x_affinity_header_when_asking_an_answer(vibe_config: VibeConfig):
    backend = FakeBackend([mock_llm_chunk(content="Response")])
    agent = build_test_agent_loop(config=vibe_config, backend=backend)

    [_ async for _ in agent.act("Hello")]

    assert len(backend.requests_extra_headers) > 0
    headers = backend.requests_extra_headers[0]
    assert headers is not None
    assert "x-affinity" in headers
    assert headers["x-affinity"] == agent.session_id


@pytest.mark.asyncio
async def test_passes_x_affinity_header_when_asking_an_answer_streaming(
    vibe_config: VibeConfig,
):
    backend = FakeBackend([mock_llm_chunk(content="Response")])
    agent = build_test_agent_loop(
        config=vibe_config, backend=backend, enable_streaming=True
    )

    [_ async for _ in agent.act("Hello")]

    assert len(backend.requests_extra_headers) > 0
    headers = backend.requests_extra_headers[0]
    assert headers is not None
    assert "x-affinity" in headers
    assert headers["x-affinity"] == agent.session_id


@pytest.mark.asyncio
async def test_updates_tokens_stats_based_on_backend_response(vibe_config: VibeConfig):
    chunk = mock_llm_chunk(content="Response", prompt_tokens=100, completion_tokens=50)
    backend = FakeBackend([chunk])
    agent = build_test_agent_loop(config=vibe_config, backend=backend)

    [_ async for _ in agent.act("Hello")]

    assert agent.stats.context_tokens == 150


@pytest.mark.asyncio
async def test_updates_tokens_stats_based_on_backend_response_streaming(
    vibe_config: VibeConfig,
):
    final_chunk = mock_llm_chunk(
        content="Complete", prompt_tokens=200, completion_tokens=75
    )
    backend = FakeBackend([final_chunk])
    agent = build_test_agent_loop(
        config=vibe_config, backend=backend, enable_streaming=True
    )

    [_ async for _ in agent.act("Hello")]

    assert agent.stats.context_tokens == 275


@pytest.mark.asyncio
async def test_no_metadata_passed_to_backend(vibe_config: VibeConfig):
    """Hard-disable invariant: this fork strips the `metadata=` kwarg from
    every backend.complete / complete_streaming / count_tokens call. The
    upstream tests for session_id / parent_session_id / entrypoint_metadata
    routing through the request body are gone with the kwarg.
    """
    backend = FakeBackend([mock_llm_chunk(content="Response")])
    agent = build_test_agent_loop(config=vibe_config, backend=backend)

    [_ async for _ in agent.act("Hello")]

    # Either the FakeBackend never received a metadata kwarg, or it was
    # explicitly None — both are acceptable. The invariant we enforce is
    # "no telemetry metadata reaches the wire".
    assert all(m is None for m in backend.requests_metadata)


@pytest.mark.asyncio
async def test_mcp_sampling_handler_uses_updated_backend_when_agent_backend_changes():
    """AgentLoop's MCP sampling handler uses current backend when backend is reassigned."""
    backend1 = FakeBackend([mock_llm_chunk(content="from-backend-1")])
    backend2 = FakeBackend([mock_llm_chunk(content="from-backend-2")])
    config = _two_model_vibe_config("devstral-latest")
    agent = build_test_agent_loop(config=config, backend=backend1)
    handler = agent._sampling_handler
    params = _make_sampling_params()
    context = MagicMock()

    result1 = await handler(context, params)
    assert isinstance(result1, CreateMessageResult)
    assert result1.content.type == "text"
    assert result1.content.text == "from-backend-1"
    assert len(backend1.requests_messages) == 1
    assert len(backend2.requests_messages) == 0

    agent.backend = backend2
    result2 = await handler(context, params)
    assert isinstance(result2, CreateMessageResult)
    assert result2.content.type == "text"
    assert result2.content.text == "from-backend-2"
    assert len(backend1.requests_messages) == 1
    assert len(backend2.requests_messages) == 1


@pytest.mark.asyncio
async def test_mcp_sampling_handler_uses_updated_config_when_agent_config_changes():
    chunk = mock_llm_chunk(content="ok")
    backend = FakeBackend([chunk])
    config1 = _two_model_vibe_config("devstral-latest")
    config2 = _two_model_vibe_config("devstral-small")
    agent = build_test_agent_loop(config=config1, backend=backend)
    handler = agent._sampling_handler
    params = _make_sampling_params()
    context = MagicMock()

    result1 = await handler(context, params)
    assert isinstance(result1, CreateMessageResult)
    assert result1.model == "mistral-vibe-cli-latest"

    agent._base_config = config2
    agent.agent_manager.invalidate_config()
    result2 = await handler(context, params)
    assert isinstance(result2, CreateMessageResult)
    assert result2.model == "devstral-small-latest"


@pytest.mark.asyncio
async def test_mcp_sampling_handler_propagates_x_affinity_header():
    """Sampling-via-MCP path: x-affinity routing header is preserved on the
    secondary backend call. The metadata kwarg is intentionally absent in
    this fork (telemetry stripped); we only assert the routing header.
    """
    backend = FakeBackend([
        [mock_llm_chunk(content="Response")],
        [mock_llm_chunk(content="Sampled response")],
    ])
    agent = build_test_agent_loop(
        config=_two_model_vibe_config("devstral-latest"),
        backend=backend,
    )

    [_ async for _ in agent.act("Hello")]

    result = await agent._sampling_handler(MagicMock(), _make_sampling_params())

    assert isinstance(result, CreateMessageResult)
    assert all(m is None for m in backend.requests_metadata)
    assert len(backend.requests_extra_headers) == 2
    sampling_headers = backend.requests_extra_headers[1]
    assert sampling_headers is not None
    assert sampling_headers["x-affinity"] == agent.session_id


def _generic_provider_vibe_config() -> VibeConfig:
    """VibeConfig with generic backend so no metadata header is sent."""
    providers = [
        ProviderConfig(
            name="mistral",
            api_base="https://api.mistral.ai/v1",
            api_key_env_var="MISTRAL_API_KEY",
            backend=Backend.GENERIC,
        )
    ]
    return build_test_vibe_config(providers=providers)


@pytest.mark.asyncio
async def test_auto_compact_propagates_x_affinity_per_call() -> None:
    """Compact triggers three backend calls (summary, recount, user turn).
    The first uses the pre-reset session_id for x-affinity routing; the
    next two use the post-reset session_id. metadata= is not asserted
    (telemetry stripped in this fork).
    """
    backend = FakeBackend([
        [mock_llm_chunk(content="<summary>")],
        [mock_llm_chunk(content="<final>")],
    ])
    config = build_test_vibe_config(
        models=make_test_models(auto_compact_threshold=1),
        providers=[
            ProviderConfig(
                name="mistral",
                api_base="https://api.mistral.ai/v1",
                api_key_env_var="MISTRAL_API_KEY",
                backend=Backend.MISTRAL,
            )
        ],
    )
    agent = build_test_agent_loop(config=config, backend=backend)
    agent.stats.context_tokens = 2
    original_session_id = agent.session_id

    [_ async for _ in agent.act("Hello")]

    assert len(backend.requests_extra_headers) == 3
    compact_headers = backend.requests_extra_headers[0]
    recount_headers = backend.requests_extra_headers[1]
    user_turn_headers = backend.requests_extra_headers[2]
    assert compact_headers is not None
    assert recount_headers is not None
    assert user_turn_headers is not None
    assert compact_headers["x-affinity"] == original_session_id
    assert recount_headers["x-affinity"] == agent.session_id
    assert user_turn_headers["x-affinity"] == agent.session_id


@pytest.mark.asyncio
async def test_generic_provider_has_no_metadata_header() -> None:
    """Non-Mistral provider does not send the metadata header."""
    backend = FakeBackend([mock_llm_chunk(content="Response")])
    config = _generic_provider_vibe_config()
    agent = build_test_agent_loop(config=config, backend=backend)

    [_ async for _ in agent.act("Hello")]

    assert len(backend.requests_extra_headers) == 1
    headers = backend.requests_extra_headers[0]
    assert headers is not None
    assert "metadata" not in headers


@pytest.mark.asyncio
async def test_provider_extra_headers_are_forwarded() -> None:
    backend = FakeBackend([mock_llm_chunk(content="Response")])
    providers = [
        ProviderConfig(
            name="custom",
            api_base="https://custom.example.com/v1",
            extra_headers={"X-Custom-Auth": "token123", "X-Org-Id": "org-456"},
        )
    ]
    models = [ModelConfig(name="test-model", provider="custom", alias="test")]
    config = build_test_vibe_config(
        active_model="test", models=models, providers=providers
    )
    agent = build_test_agent_loop(config=config, backend=backend)

    [_ async for _ in agent.act("Hello")]

    assert len(backend.requests_extra_headers) == 1
    headers = backend.requests_extra_headers[0]
    assert headers is not None
    assert headers["X-Custom-Auth"] == "token123"
    assert headers["X-Org-Id"] == "org-456"

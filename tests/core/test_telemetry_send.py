"""Hard-disable invariant for outbound telemetry.

This fork of mistral-vibe ships with telemetry hard-disabled at the source
(`TelemetryClient._is_enabled` returns False unconditionally). This test
file replaces the upstream payload-shape suite, which validated the
opposite invariant. The relevant assertions are:

- `_is_enabled()` is False regardless of `enable_telemetry` in config.
- `is_active()` is False regardless of provider/api-key state.
- `send_telemetry_event` early-returns and never instantiates an httpx
  client (so no network call can be made).

Payload-shape correctness is no longer relevant: the methods are no-ops.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock, patch

from vibe.core.telemetry.send import TelemetryClient


def _telemetry_with_config(**fields: Any) -> TelemetryClient:
    config = MagicMock()
    for k, v in fields.items():
        setattr(config, k, v)
    return TelemetryClient(config_getter=lambda: config)


class TestTelemetryHardDisabled:
    def test_is_enabled_false_when_config_says_enabled(self) -> None:
        client = _telemetry_with_config(enable_telemetry=True)
        assert client._is_enabled() is False

    def test_is_enabled_false_when_config_says_disabled(self) -> None:
        client = _telemetry_with_config(enable_telemetry=False)
        assert client._is_enabled() is False

    def test_is_active_always_false(self) -> None:
        # Even if the config and provider lookups would otherwise succeed,
        # the `_is_enabled` gate forces is_active to False.
        client = _telemetry_with_config(enable_telemetry=True)
        client._get_mistral_api_key = MagicMock(return_value="real-key")
        assert client.is_active() is False

    def test_send_telemetry_event_does_not_instantiate_httpx(self) -> None:
        client = _telemetry_with_config(enable_telemetry=True)
        with patch("vibe.core.telemetry.send.httpx.AsyncClient") as mock_client:
            client.send_telemetry_event("vibe.test", {"foo": "bar"})
            mock_client.assert_not_called()
        # The lazy `client` property attribute must remain unset.
        assert client._client is None

    def test_send_helpers_are_safe_no_ops(self) -> None:
        client = _telemetry_with_config(enable_telemetry=True)
        # Calling the public send_* methods must not raise and must not
        # instantiate a network client. Payload shape is deliberately not
        # asserted — these are no-ops by design.
        with patch("vibe.core.telemetry.send.httpx.AsyncClient") as mock_client:
            client.send_user_copied_text("hello")
            client.send_user_cancelled_action("interrupt")
            client.send_slash_command_used("help", "builtin")
            client.send_onboarding_api_key_added()
            client.send_user_rating_feedback(rating=5, model="any")
            client.send_ready(init_duration_ms=42)
            mock_client.assert_not_called()

    def test_aclose_safe_when_never_used(self) -> None:
        client = _telemetry_with_config(enable_telemetry=True)
        # No tasks or HTTP client should have been created. aclose must be
        # idempotent and not raise.
        asyncio.run(client.aclose())
        asyncio.run(client.aclose())

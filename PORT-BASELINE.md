# P0 — v2.13.0 test baseline (this machine)

> Recorded 2026-05-30 on aarch64 (Jetson, Linux 5.10.104-tegra), Python 3.12.3, uv 0.11.7.
> Baseline = unmodified `v2.13.0` (tag `ad0d5c9`), branch `feat/port-2.13`.
> Purpose: any NEW test failure during porting that is NOT in this list is a real regression.

## Result

| Suite | Command | Result |
|---|---|---|
| Main | `uv run pytest --ignore tests/snapshots` | **3469 passed, 8 skipped, 28 failed** (428s) |
| Snapshots | `uv run pytest tests/snapshots` | **110 passed, 5 failed** (173s) |

**0 real failures.** Every failure is slow-device timing — confirmed, not assumed.

## Why the 33 failures are environmental (not bugs)

Three timing mechanisms, all caused by this box being slow to cold-start the Python app:

1. **acp subprocess race (8 failures, `tests/acp/test_acp.py`)** — symptom `assert None is not None`.
   Root cause: `RESPONSE_TIMEOUT = 2.0` (tests/acp/test_acp.py:39) but `vibe-acp` cold-start
   (interpreter + full package import) measured at **~6.8s** here. `read_response_for_id` returns
   `None` on timeout instead of raising, so the timeout shows up as an assertion. Upstream x86 CI
   starts in <2s, so it passes there.
2. **textual pilot waits** — `textual.pilot.WaitForScreenTimeout: ...pending messages` (onboarding,
   mcp_command, proxy_setup, rewind snapshots). UI doesn't settle within the pilot's wait window.
3. **pytest-timeout / pexpect** — explicit `Failed: Timeout (>Ns)` and `pexpect TIMEOUT` on e2e CLI
   tests that spawn the TUI.

**Flake vs persistent:** rerunning the 28 main-suite failures serially (`--lf -n0`) passed 17 of them
— those were pure xdist CPU-contention flakes. The 11 persistent-on-this-box are: 8 acp + 2 onboarding
+ 1 e2e tool-approval, all timing.

## Persistent env-failures to ignore during porting

```
tests/acp/test_acp.py::TestSessionManagement::test_multiple_sessions_unique_ids
tests/acp/test_acp.py::TestSessionUpdates::test_agent_loop_message_chunk_structure
tests/acp/test_acp.py::TestSessionUpdates::test_tool_call_update_structure
tests/acp/test_acp.py::TestToolCallStructure::test_tool_call_request_permission_structure
tests/acp/test_acp.py::TestToolCallStructure::test_tool_call_update_approved_structure
tests/acp/test_acp.py::TestToolCallStructure::test_tool_call_update_rejected_structure
tests/acp/test_acp.py::TestToolCallStructure::test_permission_options_include_granular_labels_for_bash
tests/acp/test_acp.py::TestToolCallStructure::test_tool_call_result_update_failure_structure
tests/onboarding/test_ui_onboarding.py::test_ui_allows_manual_path_when_browser_sign_in_is_supported
tests/onboarding/test_ui_onboarding.py::test_ui_switches_to_manual_path_while_browser_sign_in_is_running
tests/e2e/test_cli_tui_tool_approval.py::test_spawn_cli_asks_bash_permission_and_shows_tool_output_after_approval[tool-call-stream]
(+ ~17 more under xdist contention — see snapshot list for the 5 snapshot ones)
```

## Testing strategy for porting (consequence)

- **Trust** unit + integration tests (the 3469) — they pass reliably and are the per-phase gate.
- **Treat** e2e / acp / snapshot **timing** failures as environmental; only investigate a NEW one.
- **P4 (agent_loop) caveat:** the acp structural assertions are currently masked by the 2.0s timeout
  on this box. When porting `acp_agent_loop.py`, verify those tests with a locally bumped
  `RESPONSE_TIMEOUT` (e.g. env override or temporary patch to ~10s) so a real regression isn't hidden.

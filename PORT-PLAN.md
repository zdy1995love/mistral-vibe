# v2.13 Port Execution Checklist

> Clean-room re-port of the mistral-vibe fork's custom features onto upstream **v2.13**. Target tree: `/home/zdy/mistral-vibe-2.13`. Source of truth for fork behavior: the current fork working tree. This doc is file-level and ordered; follow phases in sequence because later phases depend on shared data-contract changes landed in earlier ones.

## 1. Executive Summary

- **Total estimated LOC to (re)write:** ~3,800 LOC across 11 feature specs (sum of per-feature estimates: 55 + 420 + 625 + 15 + 120 + 520 + 420 + 760 + 650 + 170 + 72 + cross-cutting wiring overlap). Net distinct LOC is lower (~3,000) because several specs share the same `types.py` / `agent_loop.py` / `models.py` edits — **do those shared edits once**.
- **What upstream now does natively (big wins):** v2.13 ships a full native plan flow (`PlanSession`, `PlanReview*` events, `PlanFileMessage` live-edit UI, Ctrl+G open-in-editor, profile-based PLAN read-only via `_plan_overrides()`), native `~/.agents/skills` discovery (`AGENTS_HOME` + `user_skills_dirs`), native reasoning history re-injection (`LLMMessage.reasoning_content` + `ReasoningAdapter`), native `AutoCompactMiddleware`/`COMPACT` wiring, native `compaction_prompt_id`, and native shift+tab PLAN cycling with a `switch_agent_generation` guard. These let us **delete** the fork's `superpowers/` bundle + loader, the fork's `PlanSession` copy, fork history-reinjection assumptions, and the write-tool branch of the plan gate.
- **Biggest risks (in order):**
  1. **Plan-mode semantic collision (P5, RED):** v2.13 is *review-in-place*; the fork is *wipe-and-fork*. `PlanReviewRequestedEvent` still fires before the fork wipe — must suppress/sequence or the UI mounts a `PlanFileMessage` we immediately destroy.
  2. **`agent_loop.py` bundle splitting (P4, RED):** the fork's +556 diff bundles unrelated features (`_sanitize_tool_call_arguments`, `_promote_inline_tool_calls`, telemetry metadata removal). Do **not** drop v2.13's `metadata=...model_dump()` plumbing.
  3. **`assert_never` exhaustiveness (P3/P4):** adding `BottomApp.AgentsPicker`/`StatTimeline` without the matching `_focus_current_bottom_app` case crashes at runtime.
  4. **`CompactMessage.set_complete()` signature change (P5):** v2.13 is `(*, old_session_id, new_session_id)`, not `(old_tokens, new_tokens)` — the `/compact --micro` branch breaks if copied verbatim.
  5. **`_toggle_plan_mode` deadlock (cross):** fork uses `asyncio.run()`; v2.13 requires `run_coroutine_threadsafe`.
  6. **`ThinkingLevel` narrowing breaks upstream tests (P1):** narrowing to `['off','high']` breaks `test_thinking_picker_shows_all_levels` and `TestReasoningEffort` parametrize.

## 2. Feature Matrix

| Feature | Phase | Difficulty | Est LOC | Confidence | Key v2.13 anchor |
|---|---|---|---|---|---|
| cached-tokens | P1 | 🟢 green | 55 | high | `LLMUsage` `types.py:332`; `_update_stats` `agent_loop.py:1454` |
| reasoning-two-tier | P1 | 🟡 yellow | 420 | high | `ThinkingLevel` `_settings.py:362`; `set_thinking` `:952` |
| vllm-extractors | P1 | 🟡 yellow | 625 | high | `GenericBackend.complete` `generic.py:278`; `complete_streaming` `:346` |
| telemetry-off | P2 | 🟢 green | 15 | high | `_is_enabled()` `send.py:88-92` |
| output-styles | P3 | 🟢 green | 120 | high | `get_universal_system_prompt` `system_prompt.py:308/319` |
| agents-ui | P3 | 🟡 yellow | 520 | high | `BottomApp` `app.py:216`; `_focus_current_bottom_app` `:2388` |
| stat-timeline-ui | P4 | 🟡 yellow | 420 | high | `AgentStats` `types.py:47`; `StreamingMessageBase` `messages.py:114` |
| agent-loop-hooks | P4 | 🔴 red | 760 | high | `_update_stats` `:1454`; `_setup_middleware` `:751`; `_execute_tool_call` `:1100` |
| plan-mode | P5 | 🔴 red | 650 | high | `_plan_overrides()` `models.py:100-107`; `_handle_session_plan_events` `agent_loop.py:972` |
| microcompact | P5 | 🟡 yellow | 170 | high | `AutoCompactMiddleware` add-point `agent_loop.py:751`; `CompactMessage.set_complete` `compact.py:33` |
| app-commands-wiring | P3/P5 | 🔴 red | 420 | high | `BottomApp` `:216`; `_handle_agent_loop_turn` `:1421`; `commands.py:110` |
| skills-relocation | P6 | 🟢 green | 72 | high | `user_skills_dirs` `_harness_manager.py:97-104`; `GLOBAL_AGENTS_SKILLS_DIR` `_paths.py:9` |

---

## P1 — Local-model essentials

> Shared dependency: `cached_prompt_tokens` on `LLMUsage` must land before any backend or `_update_stats` work. Do **cached-tokens** first.

### P1a — cached-tokens (🟢 55 LOC)

**MODIFY**
- `vibe/core/types.py` — `LLMUsage` (anchor `class LLMUsage(BaseModel)` ~L332): add `cached_prompt_tokens: int = 0`, carry through `__add__`. `AgentStats` (L47): add `session_cached_tokens: int = 0`, `last_turn_cached_tokens: int = 0`, `cleared_tool_results: int = 0`, `turns: list[TurnRecord] = Field(default_factory=list)`; add `TurnRecord` model (index, prompt_tokens, cached_tokens, completion_tokens, duration, started_at, tools). `reset_context_state()` (L128): reset `last_turn_cached_tokens`.
- `vibe/core/llm/backend/anthropic.py` — add module-level `_build_usage_from_message_response(data)` mapping `cache_read_input_tokens -> cached_prompt_tokens`; call at all 3 sites: `parse_response` (~L166), `_handle_message_start` (~L299), `AnthropicAdapter._parse_message_start` (~L516).
- `vibe/core/llm/backend/generic.py` — `OpenAIAdapter.parse_response` (~L207): read `prompt_tokens_details.cached_tokens` into `cached_prompt_tokens`.
- `vibe/core/llm/backend/openai_responses.py` — add `input_tokens_details` to `_ResponsesUsageData` TypedDict (L31); add module-level `_build_usage()`; delegate `_usage_from_response` (L129) to it.
- `vibe/core/agent_loop.py` — `_update_stats` (L1454): accumulate `cached_prompt_tokens` into `session_cached_tokens`/`last_turn_cached_tokens`; append `TurnRecord`. Import `TurnRecord`.

**MIGRATE TESTS:** `tests/backend/test_cache_tokens.py` (7 tests, verbatim — covers all 3 extraction sites + null/missing edge cases).

**Risks:** the message_start path passes a nested `message` dict — verify the helper's `data.get('usage', {})` resolves correctly at all 3 call sites. `test_acp/test_usage_update.py` asserts `cached_read_tokens is None` — verify `FakeBackend` still passes `cached_prompt_tokens=0`.

### P1b — reasoning-two-tier (🟡 420 LOC)

**CREATE**
- `vibe/core/llm/backend/think_tag_extractor.py` (verbatim, 99 LOC).
- `vibe/core/llm/backend/mistral_text_tool_call_extractor.py` (verbatim, 234 LOC).

**MODIFY**
- `vibe/core/config/_settings.py` — narrow `ThinkingLevel` to `Literal['off','high']` (override L362); add `_THINKING_TEMPERATURE = {'high':0.7,'off':0.3}`; extend `set_thinking()` (L952) to co-update `ModelConfig.temperature` in both the found-entry and materialize-all branches; add `send_thinking_blocks: bool = False` + `parse_text_tool_calls: bool = False` to `ProviderConfig`; default `enable_telemetry = False`.
- `vibe/core/llm/backend/generic.py` — expand `_reasoning_to_api()` (L68-73: strip from non-assistant roles + encode thinking blocks when `send_thinking_blocks`); add `reasoning_effort` param to `build_payload`/`prepare_request` (L82-127); add the 4 helpers (`_apply_think_extractor_oneshot/_streaming`, `_completed_to_tool_calls`, `_apply_tool_call_text_extractor_streaming`); wire extractors into `complete`/`stream_complete` (L260-340).
- `vibe/core/llm/backend/reasoning_adapter.py` — add `reasoning_effort: str|None=None` to `_build_payload` (L74)/`prepare_request` (L109); `reasoning_effort` takes precedence over `thinking`.
- `vibe/cli/textual_ui/widgets/thinking_picker.py` — **no code change** (consumes narrowed Literal automatically).

**MIGRATE TESTS**
- `tests/cli/test_ui_config_and_model_picker.py` — rename `test_thinking_picker_select_level`→`_select_high`, drop redundant multi-step test, adjust navigation counts and `'low'/'medium'`→`'high'`. **Must also update `test_thinking_picker_shows_all_levels`** (asserts 5 levels — will fail).
- `tests/core/test_config_resolution.py` — `_ModelConfigOverrides` → `Literal['off','high']`; `set_thinking('max')`→`('high')`; `TestMigrateMistralVibeCliLatestDefaults` `'low'`→`'high'`.
- `tests/backend/test_generic_think_extractor.py` (new, 53 LOC, verbatim).
- `tests/llm/test_think_tag_extractor.py` (new, verbatim).
- `tests/backend/test_mistral_text_tool_call_extractor.py` (new, verbatim).
- `tests/backend/test_backend.py` — `TestReasoningEffort` parametrizes `('off','low','medium','high')`; `'low'/'medium'` become invalid Literals — drop those entries or add a deprecation shim.

**Risks:** temperature coupling conflicts with v2.13 `MistralBackend` forcing `temperature=1.0` when `reasoning_effort` is active (`mistral.py:281-283,359-361`) — decide whether to skip co-update for Mistral providers or document the override. Co-update overwrites user-set temperature when toggling thinking — behavioral regression vs v2.13. Keep `send_thinking_blocks=False` default (extractor opt-in, untested on Mistral API).

### P1c — vllm-extractors (🟡 625 LOC)

> Overlaps P1a (`LLMUsage.cached_prompt_tokens`) and P1b (extractor files, `ProviderConfig` flags, `generic.py` reasoning changes). **Land P1a+P1b first**, then this adds only the agent_loop sanitize/promote layer + remaining generic.py wiring.

**MODIFY**
- `vibe/core/agent_loop.py` — add module-level `_sanitize_tool_call_arguments`, `_generate_synthetic_tool_call_id`, `_match_trailing_inline_tool_call`, `_promote_inline_tool_calls` (verbatim, fork L200-371). In `_chat_nonstreaming` (anchor `self.messages.append(processed_message)` v2.13 L1368): insert sanitize+promote between `format_handler` processing and append. In `_chat_streaming` (anchor `self.messages.append(chunk_agg.message)` v2.13 L1440): run sanitize+promote before append.
- `vibe/core/llm/backend/anthropic.py` — add `reasoning_effort: str|None=None` + `del reasoning_effort` stub to `AnthropicAdapter.prepare_request` to match the interface.

**MIGRATE TESTS:** `tests/llm/test_think_tag_extractor.py`, `tests/backend/test_generic_think_extractor.py`, `tests/backend/test_mistral_text_tool_call_extractor.py`, `tests/test_promote_inline_tool_calls.py` (187 LOC), `tests/test_tool_call_sanitize.py` (113 LOC) — all verbatim.

**Risks:** **type ordering** — `types.py` `cached_prompt_tokens` must precede all `usage +=` callers. Injection points at v2.13 L1368/L1440 must be **verified against actual line numbers** (v2.13 `_chat_streaming` has more code: correlation_id, chunk_agg). Use `getattr(self._provider, 'parse_text_tool_calls', False)` defensive pattern. **Do NOT narrow `ThinkingLevel`'s effect on `reasoning_effort` mapping** — use a mapping dict (like `MistralBackend._THINKING_TO_REASONING_EFFORT`) not the fork's `model.thinking != 'off'` ternary, to preserve `low/medium/max`.

---

## P2 — telemetry-off (🟢 15 LOC)

**MODIFY**
- `vibe/core/telemetry/send.py` — `_is_enabled()` (L88-92): replace try/except body with `return False`; update docstring.
- `vibe/core/config/_settings.py` — ship `enable_telemetry = false` and/or `[experiments] enable = false` default (defense-in-depth; experiments are double-gated on `config.enable_telemetry and config.experiments.enable` in `experiments/session.py`).

**Optional belt-and-suspenders:** hard-gate `setup_tracing()` in `vibe/core/tracing.py` (L24) with an unconditional `return` — `tracing.py` reads `config.enable_telemetry` **directly**, NOT through `_is_enabled()`, so the `_is_enabled` patch alone does **not** disable otel.

**MIGRATE TESTS:** `tests/core/test_telemetry_send.py` — **REPLACE** the 859-line upstream payload-shape suite with the fork's 75-line `TestTelemetryHardDisabled` class (the upstream suite tests the now-dead enabled-send path). Do **NOT** port `tests/core/experiments/` — those mock `enable_telemetry=True` and still pass.

**Risks:** `ExperimentsConfig` has no own `env_prefix`, so `VIBE_EXPERIMENTS_ENABLE` does **not** flow — set via `[experiments] enable=false` in config.toml. Replacing the 859-line suite loses payload/retry/aclose coverage (intentional). Verify `tests/core/experiments/test_telemetry_integration.py` doesn't assert on `send_telemetry_event` side effects.

---

## P3 — Output styles, agents UI, command shell

### P3a — output-styles (🟢 120 LOC)

**CREATE**
- `vibe/core/prompts/styles/{default,concise,learner}.md` (verbatim).
- `vibe/core/output_styles/__init__.py` + `vibe/core/output_styles/manager.py` (verbatim — `VIBE_ROOT`/`VIBE_HOME` imports unchanged).
- `tests/core/output_styles/__init__.py` (empty) + `tests/core/output_styles/test_manager.py` (verbatim).

**MODIFY**
- `vibe/core/config/_settings.py` — add `output_style: str = 'default'` after `auto_compact_threshold` (v2.13 L526).
- `vibe/core/system_prompt.py` — add `_resolve_output_style_section(config)` (verbatim). In `get_universal_system_prompt()` (L308), replace the first `sections = [_interpolate_prompt(_resolve_system_prompt(config, experiment_manager))]` (L319) with:
  ```python
  sections: list[str] = list(_resolve_output_style_section(config))
  sections.append(_interpolate_prompt(_resolve_system_prompt(config, experiment_manager)))
  ```
  **Keep the `experiment_manager` param** — do not drop it.
- `vibe/cli/commands.py` — add `'style'` `Command(aliases=frozenset(['/style']), description='List or switch output style', handler='_set_output_style')` after the `'theme'` entry (L177).
- `vibe/cli/textual_ui/app.py` — add `_set_output_style()` (verbatim) near `_show_theme()` (~L1794). No `BottomApp` enum change (text-based command).

**MIGRATE TESTS:** `tests/cli/textual_ui/test_style_command.py` (verbatim — `build_test_vibe_config(output_style=...)` works via `**kwargs`).

**Risks:** must keep `experiment_manager` wiring when prepending output style. `TestStyleSwitchInPlanMode` uses `BuiltinAgentName.PLAN` + `agent_profile` — grep-confirm both exist in v2.13.

### P3b — agents-ui (🟡 520 LOC)

> Shares `manager.py` `_pre_plan_profile`/`switch_profile` stash and `models.py` `_PLAN_BASH_READ_ONLY_ALLOWLIST`/`_plan_overrides()` changes with **P5**. **Coordinate** — apply each shared edit once.

**CREATE**
- `vibe/cli/textual_ui/widgets/agents_picker.py` (verbatim, 140 LOC — verify `NoMarkupStatic` import path).
- `vibe/cli/textual_ui/agent_editor.py` (verbatim, 70 LOC — `resolve_edit_path`, uses `AgentManager._search_paths` + `get_harness_files_manager().sources`).
- `tests/cli/test_agent_editor.py`, `tests/cli/test_ui_agents_picker.py`, `tests/snapshots/test_ui_snapshot_agents_picker.py` (all verbatim; regenerate snapshots).

**MODIFY**
- `vibe/core/agents/models.py` (L38 enum, L201 dict) — add `BuiltinAgentName.GENERAL_PURPOSE = 'general-purpose'`; add `_NON_PLAN_BASE_DISABLED = ['exit_plan_mode','enter_plan_mode']` applied to DEFAULT/ACCEPT_EDITS/AUTO_APPROVE; add `enter_plan_mode` to LEAN `base_disabled`; add `_PLAN_BASH_READ_ONLY_ALLOWLIST`; update `_plan_overrides()` to `'ask'` + bash allowlist; add `GENERAL_PURPOSE` `AgentProfile`, register in `BUILTIN_AGENTS`. *(plan-mode-shared — coordinate with P5)*
- `vibe/core/prompts/__init__.py` — add `GENERAL_PURPOSE = auto()` to `PromptId` enum (~L26) + register `general_purpose` prompt.
- `vibe/core/agents/manager.py` — add `_runtime_registered: set[str]`, `_pre_plan_profile`, `pre_plan_profile` property, `switch_profile()` PLAN stash, `register_agent()` tracking, `reload_from_disk()`. *(items b/c/d shared with P5)*
- `vibe/cli/commands.py` — add `'agents'` Command (handler `_show_agents`).
- `vibe/cli/textual_ui/app.py` — add `import shlex, subprocess` (or delegate to native `external_editor.py`); `AgentsPicker = auto()` to `BottomApp` (L216); import `AgentsPickerApp`; `_show_agents()`, `_switch_to_agents_picker_app()`, the 3 `on_agents_picker_app_*` handlers, `_handle_agents_picker_app_escape()`; **add `AgentsPicker` case to `_focus_current_bottom_app` match before `assert_never` (L2388)**; add escape branch to `_try_interrupt_bottom_app_escape()` (L2713).
- `vibe/cli/textual_ui/app.tcss` — append 7 `#agentspicker-*` rules (~48 lines).

**MIGRATE TESTS:** `tests/core/test_agents.py` — add only the 6 new `reload_from_disk` methods (do NOT duplicate existing `TestAgentProfile`/basic `TestAgentManager`).

**Risks:** `assert_never` — case arm mandatory in same commit. Shared `switch_profile`/`_plan_overrides` with P5 — port once. `agent_editor.py` reads private `_search_paths` (confirmed v2.13 manager L29) — consider a public property. Snapshots will fail first run (Textual version bump) — plan a regen pass. Verify `external_editor.py` / `subprocess` availability before hand-rolling the edit invocation.

### P3c — app-commands-wiring shell (UI half — P3 portion)

> The command registry + BottomApp + picker plumbing. The fork-to-dev loop and `_toggle_plan_mode` belong to **P5** (see below). Do the non-plan command registrations here; defer plan/micro branches until their backends land.

**MODIFY**
- `vibe/cli/commands.py` — rename `'status'`→`'stat'`, add `'/status'` alias, handler `_show_stat`; add `'agents'`, `'plan'` (handler `_toggle_plan_mode` — backend lands P5), `'style'` entries inside `_build_commands()` (status L110, after compact L99).
- `vibe/cli/textual_ui/app.py`:
  - `BottomApp`: add `AgentsPicker`, `StatTimeline` (L216).
  - imports: `AgentsPickerApp`, `StatOverviewMessage`, `StatTimelineApp`, `PlanModeIndicator`, `BuiltinAgentName`.
  - `compose()` (L519-522): `yield PlanModeIndicator()` between `PathDisplay` and the `NoMarkupStatic` spacer.
  - `on_mount()` (L524-571): `query_one(PlanModeIndicator).set_active(active_profile.name == BuiltinAgentName.PLAN)`.
  - `_focus_current_bottom_app` (L2388): add `AgentsPicker` + `StatTimeline` cases before `assert_never`.
  - `_try_interrupt_bottom_app_escape` (L2713): add `AgentsPicker`/`StatTimeline` escape branches before the Rewind branch.
  - `build_history_widgets` loop (~L1316-1318): add `await widget.stop_stream()` after `write_initial_content()` (restored-message finalization fix).
  - `_on_profile_changed()` (L2846): add `self._plan_indicator.set_active(...)`.
  - `_cycle_agent()` finally (L2903): change `call_from_thread(self._refresh_banner)` → `call_from_thread(self._on_profile_changed)`.

**MIGRATE TESTS:** `tests/cli/test_commands.py` — **extend** (do not replace) with agents/plan/stat/style registration cases.

**Risks:** `BottomApp` naming convention is `ClassName minus 'App'` — `AgentsPickerApp→AgentsPicker`, `StatTimelineApp→StatTimeline` must be exact (dynamic lookup via `BottomApp[type(w).__name__.removesuffix('App')]`). `stop_stream` fix may double-call for widgets `event_handler.finalize_streaming` already stopped — verify idempotency.

---

## P4 — Stats data contract, stat UI, agent-loop hooks

> P4a (data contract in `types.py`) is the prerequisite for both the stat UI and the agent-loop hooks. If P1a already landed the `LLMUsage`/`AgentStats`/`TurnRecord` edits, P4a is a no-op — **do not double-apply.**

### P4a — stat-timeline-ui (🟡 420 LOC)

**MODIFY (data contract — shared with P1a):**
- `vibe/core/types.py` — `TurnRecord` + `AgentStats.{session_cached_tokens,last_turn_cached_tokens,cleared_tool_results,turns}` + `LLMUsage.cached_prompt_tokens`. *(If P1a done, skip.)*
- `vibe/cli/textual_ui/widgets/messages.py` — full `_PlainTextStreamAdapter` rework (anchor `StreamingMessageBase` L114, `ReasoningMessage` L202): add `import time`, `_STREAM_FLUSH_INTERVAL_S = 0.033`, `_PlainTextStreamAdapter`; class-level `_streaming_static/_finalized/_flush_interval_s/_last_flush_monotonic`; replace `_get_markdown`/`_ensure_stream` with `_create_streaming_static`/`_build_markdown_widget`/`_ensure_stream`→adapter; rewrite `append_content` (throttle gate); rewrite `stop_stream`→`_finalize_to_markdown`; add `_finalize_to_markdown`; update `AssistantMessage.compose` + `ReasoningMessage.compose`/`set_collapsed` (mid-stream static vs post-stream Markdown). **Companion:** `event_handler.py` `collapsed=False` for `ReasoningMessage` (from reasoning-two-tier cluster — never auto-collapse reasoning).

**CREATE**
- `vibe/cli/textual_ui/widgets/stat_overview.py` (verbatim — deps `ExpandingBorder` L41, `AgentStats`).
- `vibe/cli/textual_ui/widgets/stat_timeline.py` (verbatim — deps `AgentStats`, `TurnRecord`).

**MODIFY (app + commands + css):**
- `vibe/cli/commands.py` — `stat`/`/stat`/`/status` entry (see P3c).
- `vibe/cli/textual_ui/app.py` — `_show_stat()` + `_switch_to_stat_timeline_app()` + `on_stat_timeline_app_cancelled()` + `_handle_stat_timeline_app_escape()`; **remove `_show_status()`** (dead). (`BottomApp`/match/escape plumbing from P3c.)
- `vibe/cli/textual_ui/app.tcss` — add `.stat-overview-*` + `#stat-timeline-*` blocks; **translate colors** `ansi_bright_black→$foreground-muted`, `ansi_blue→$primary`.

**MIGRATE TESTS:** `tests/cli/test_stat_overview.py`, `tests/cli/test_stat_timeline.py`, `tests/cli/test_show_stat_handler.py`, `tests/cli/textual_ui/test_streaming_message_buffer.py` (all verbatim; last one depends on the messages.py rework).

**Risks:** `assert_never` (StatTimeline case). CSS theming: fork uses literal ansi names; v2.13 uses `$`-vars with a theme switcher — must translate or light theme breaks. `MarkdownStream` swap (Textual 8.2.7) must not regress mid-stream collapse fidelity. `TurnRecord.tools` populated post-turn → empty cells until next refresh tick (coupling with P4b).

### P4b — agent-loop-hooks (🔴 760 LOC)

> The engine for stats collection, microcompact trigger, and plan-mode dispatch. **Split out the bundled unrelated features** (sanitize/promote → P1c; metadata removal → keep v2.13's plumbing). Ordering inside this phase is strict.

**STEP 0 — prereq deps (MODIFY):**
- `vibe/core/types.py` — `TurnRecord`/`AgentStats` fields/`LLMUsage.cached_prompt_tokens`. *(If P1a/P4a done, skip.)*

**STEP 1 — cached-token source (MODIFY):**
- `vibe/core/llm/backend/mistral.py` — add `cached_prompt_tokens=details.get('cached_tokens',0)` from `usage.prompt_tokens_details` to BOTH `LLMUsage` constructions (non-stream ~L318, stream ~L397). **Verify v2.13 SDK usage object still exposes `prompt_tokens_details`.**

**STEP 2 — stats collection (MODIFY):**
- `vibe/core/agent_loop.py` — `_update_stats` (L1454): add 3 cached lines + `stats.turns.append(TurnRecord(...))` (`started_at=time.time()-time_seconds`, `index=stats.steps`). Add `_record_dispatched_tool` and call it right after `tool_calls_agreed += 1` (L1132).

**STEP 3 — microcompact trigger (depends on P5 microcompact module):**
- `vibe/core/config.py` — add `micro_compact_ratio`, `micro_keep_last`.
- `vibe/core/agent_loop.py` — `_setup_middleware` (L751): `self.middleware_pipeline.add(MicroCompactMiddleware())` **immediately before** `AutoCompactMiddleware()`, **after** `TokenLimitMiddleware`. (Ordering is load-bearing — micro mutates `context_tokens` down so AutoCompact re-reads reduced count.)

**STEP 4 — plan-mode deps (MODIFY):**
- `vibe/core/tools/base.py` — add `mutates_state: ClassVar[bool] = True` to `BaseTool`; `request_fork_to_dev_callback` to `InvokeContext` (L44).
- `vibe/core/tools/builtins/*.py` — per-tool `mutates_state` overrides: `bash/search_replace/write_file/task=True`; `read_file/grep/webfetch/websearch/todo/skill/ask_user_question/exit_plan_mode/enter_plan_mode=False`. **Audit the full v2.13 builtins list** — a missed tool defaults to `True` and gets blocked in PLAN.
- `vibe/core/agents/manager.py` — `_pre_plan_profile`/`pre_plan_profile`/`switch_profile` stash. *(shared with P3b/P5 — port once.)*

**STEP 5 — plan dispatch core (MODIFY `agent_loop.py`):**
- `__init__` (L234-326): add `_pending_fork_to_dev`, `_plan_modified_in_turn`.
- `_execute_tool_call` (L1100-1107): plan write-gate at top (after `get(tool_instance)`, before `_should_execute_tool`) — `_PLAN_GATE_BYPASS_TOOLS`, `resolve_permission ALWAYS` bypass, `task→AgentSafety.SAFE` carve-out. Add `request_fork_to_dev_callback=self.request_fork_to_dev` to `InvokeContext` (L1141-1154).
- `_handle_tool_response` (L1275): `_plan_modified_in_turn` detection block after `messages.append`, before telemetry.
- `_conversation_loop` (L931): set `_plan_modified_in_turn=False` at top of try (~L896); fork-break logic (`if _pending_fork_to_dev is not None: should_break_loop=True` / `elif should_break_loop: await _maybe_prompt_plan_confirmation()`); gate hooks block with `and _pending_fork_to_dev is None`.
- `_handle_middleware_result` INJECT_MESSAGE (L788): prepend synthetic assistant ack when `messages[-1].role == Role.tool`.
- `switch_agent` (L1755): `leaving_plan` capture + `self._plan_session = PlanSession()` rotation. `clear_history` (L1655): wipe `_plan_session/_pending_fork_to_dev/_plan_modified_in_turn/agent_manager._pre_plan_profile`. `_clean_message_history` (L1536): `_close_orphan_trailing_tool_message()`.
- Add `_maybe_prompt_plan_confirmation`, `request_fork_to_dev`, `pending_fork_to_dev` property, `fork_to_dev`.

**STEP 6 — sparse reminders (MODIFY):**
- `vibe/core/middleware.py` — `make_plan_agent_sparse_reminder()`; extend `ReadOnlyAgentMiddleware.__init__` (L193) with `sparse_reminder`/`sparse_every_n_turns`/`_turns_since_reminder`/`sparse_reminder_text`.
- `vibe/core/agent_loop.py` `_setup_middleware` (L755-768): wire `sparse_reminder=lambda: make_plan_agent_sparse_reminder(self._plan_session.plan_file_path_str)`, `sparse_every_n_turns=5`.

**STEP 7 — acp re-entry (MODIFY):**
- `vibe/acp/acp_agent_loop.py` — wrap the `act()` call site (grep `async for ... in session.agent_loop.act(` — anchor `class VibeAcpAgentLoop` ~L928) in a while-loop that calls `fork_to_dev()` while `pending_fork_to_dev` is set.

**MIGRATE TESTS:** `tests/core/test_agent_loop_stats.py`, `tests/core/test_stats.py` (after STEP 0/2); `tests/core/compact/test_micro.py` (after STEP 3); `tests/core/tools/test_mutates_state.py` (after STEP 4). **Out of scope for P4:** `tests/test_turn_summary.py` (separate narrator feature), `tests/cli/test_plan_command.py`/`test_show_stat_handler.py`/`test_stat_*` (CLI consumers — P3/P5).

**Risks:** v2.13 has **no** native replacement for any group — pure additive. **Split the bundle** — keep v2.13's `metadata=...model_dump()` at L1352/L1417. Concurrent tool exec (`_run_tools_concurrently` L1231-1273): `_update_stats` creates the TurnRecord in `_chat` before any dispatch, so `stats.turns[-1]` is valid — verify ordering. `mutates_state` must be re-applied to **every** builtin. Verify v2.13 `exit_plan_mode.py` callback wiring (`switch_agent_callback` vs `request_fork_to_dev`) and guard ordering vs `_handle_session_plan_events` (L972) to avoid duplicate confirmation. acp anchor may have moved — grep, don't trust line numbers.

---

## P5 — Plan-mode redesign + microcompact

### P5a — DECISION GATE (do this first)

Choose the **hybrid layering**: keep upstream native PLAN read-only (permission-based) + native PlanReview UI, and layer ON TOP only: (a) hard `mutates_state` gate scoped to **bash/task/mcp** (NOT write_file/search_replace — upstream `_plan_overrides()` covers those), (b) fork-to-dev exit replacing native in-place switch, (c) sparse reminders, (d) `/plan` toggle + `enter_plan_mode` tool + `PlanModeIndicator`. **Document that fork-to-dev REPLACES native review-then-implement-in-place** and reconcile the `PlanReviewRequested` mount on the wipe path.

### P5b — plan-mode (🔴 650 LOC)

**CREATE**
- `vibe/core/tools/builtins/enter_plan_mode.py` (verbatim, adjust imports). Register in v2.13 builtin registry. **ENABLED outside PLAN, disabled IN PLAN** (inverse of `exit_plan_mode`).
- `vibe/cli/textual_ui/widgets/plan_mode_indicator.py` (verbatim — verify no DOM-id/CSS collision with native `PlanFileMessage`).

**MODIFY**
- `vibe/core/tools/base.py` — `request_fork_to_dev_callback` on `InvokeContext` (L44; keep `permission_store`). *(shared with P4b STEP 4.)*
- `vibe/core/agents/manager.py` — `_pre_plan_profile`/`pre_plan_profile`/`switch_profile` stash (L93-94). *(shared P3b/P4b — port once.)*
- `vibe/core/agent_loop.py` — plan gate + fork-to-dev + plan_session rotation + `_plan_modified_in_turn` + InvokeContext callback + reconcile `_handle_session_plan_events` (L972: suppress/short-circuit `PlanReviewRequestedEvent` on the fork-staged path). *(shared with P4b STEP 5 — these are the same edits; do once.)*
- `vibe/core/tools/builtins/exit_plan_mode.py` — port the **run()-body delta only** onto upstream's class: plan-file read/validate (+ optional `_find_recent_plan_file` fallback + empty guard), `target_profile` = ACCEPT_EDITS vs `pre_plan_profile`, call `request_fork_to_dev_callback`. Keep upstream `footer_note` (Ctrl+G) + three-choice question. Add `mutates_state=False`.
- `vibe/core/middleware.py` — sparse reminder (shared with P4b STEP 6) + parallel-task-subagent text in `make_plan_agent_reminder`.
- `vibe/cli/commands.py` — `'plan'` Command (handler `_toggle_plan_mode`).
- `vibe/cli/textual_ui/app.py` — `_toggle_plan_mode()` using **`run_coroutine_threadsafe`** (not `asyncio.run`); `_handle_pending_fork()`; while-True wrap of the `act()` driver; `PlanModeIndicator` mount/`set_active`; reuse existing `switch_agent_generation` guard.

**DELETE (native now):** fork's `vibe/core/plan_session.py` copy (use upstream `PlanSession`). Trim write_file/search_replace from `_PLAN_GATE_BYPASS_TOOLS` gate. Do not re-create `exit_plan_mode` class scaffolding, PlanReview events, PlanFileMessage, or PLAN cycle ordering — all native.

**MIGRATE TESTS:** `tests/test_agent_plan_mode_dispatch.py` (gate + fork-to-dev — rework write/search_replace cases if trimmed from gate); merge fork `test_exit_plan_mode.py` into v2.13 `tests/tools/test_exit_plan_mode.py` (keep fallback/empty-guard/pre_plan_profile cases; reconcile with `test_yes_uses_switch_agent_callback`/`test_result_does_not_include_plan_content`); `tests/tools/test_enter_plan_mode.py` (wholesale); `tests/cli/test_plan_command.py` (adapt to `CommandRegistry`/while-loop); merge sparse cases into `tests/test_middleware.py`. **DROP** `tests/test_system_prompt.py` from P5 (output-style — P3a). Rely on upstream `tests/core/test_plan_session.py`.

**Risks (highest):** **semantic collision** (review-in-place vs wipe-and-fork) — `PlanReviewRequestedEvent` fires before the wipe; suppress or the UI flickers/leaks a file watcher. **double read-only enforcement** — trim write tools from gate (Step 0). **`enter_plan_mode` base_disabled inversion** — wrong polarity lets the model loop. **`_toggle_plan_mode` deadlock** — must use `run_coroutine_threadsafe`. **`message_index=1` assumption** — v2.13 windowing (`_tool_call_map`, backfill) more elaborate; verify rewind/windowing. **auto_title re-fire** — guard `is_initial_turn` so the seed iteration doesn't retitle. MEMORY caution: prior sparse-reminder/prepend-ack test alignment may resurface.

### P5c — microcompact (🟡 170 LOC)

**CREATE**
- `vibe/core/microcompact.py` — **recommend this name** over re-creating the `compact/` package (v2.13 owns `compaction.py`; a sibling `compact/` is confusing). Copy `micro_compact()` + `MicroCompactMiddleware` + `CLEARABLE_TOOLS` + `_CLEARED_MARKER` verbatim from fork `vibe/core/compact/micro.py`. Imports resolve: `ConversationContext/MiddlewareResult/ResetReason` from `middleware`; `AgentStats/MessageList/Role` from `types`.
- `tests/core/microcompact/__init__.py` + `tests/core/microcompact/test_micro.py` — fix import `vibe.core.compact.micro` → `vibe.core.microcompact`.

**MODIFY**
- `vibe/core/types.py` — `cleared_tool_results: int = 0` on `AgentStats` after `context_tokens` (L56). *(If P1a/P4a done, skip.)*
- `vibe/core/config/_settings.py` — `micro_compact_ratio: float = 0.7`, `micro_keep_last: int = 2` after `auto_compact_threshold` (L526).
- `vibe/core/agent_loop.py` — import + register `MicroCompactMiddleware()` before `AutoCompactMiddleware`, after `TokenLimitMiddleware` (L751). *(same as P4b STEP 3.)*
- `vibe/cli/textual_ui/app.py` — re-graft `--micro` branch at the **TOP** of `_compact_history()` (L2164), before the async-task spawn and `_agent_running` guard; bail if `threshold<=0`; call `micro_compact()` directly; **report tokens freed via a status/info message** — **NOT** `CompactMessage.set_complete(old_tokens=,new_tokens=)` (signature is now `(*, old_session_id, new_session_id)`). `return` before the full-compact path.
- `vibe/core/skills/builtins/vibe.py` — add the two config doc lines near `compaction_prompt_id` (~L77).

**MIGRATE TESTS:** `tests/core/microcompact/test_micro.py` (9 tests, import fix only). **ADD** an integration test asserting `MicroCompactMiddleware` registered before `AutoCompactMiddleware` and the async `/compact --micro` path works (guards the `set_complete` regression and the ordering invariant). Run `tests/core/test_compaction.py` + `tests/test_agent_auto_compact.py` to confirm no full-compaction regression.

**Risks:** **HIGH** — `set_complete` signature change; rewrite the `--micro` UI feedback (micro creates no new session, so session-id display is semantically wrong). **MEDIUM** — async `_compact_history` refactor: branch must `return` before the task spawn or it double-runs. **MEDIUM** — middleware ordering invariant (no test catches a reorder unless the added ordering test exists). **LOW** — `micro_keep_last=0` slicing quirk already guarded; preserve verbatim.

---

## P6 — skills-relocation (🟢 72 LOC)

> v2.13 natively discovers `~/.agents/skills` (`AGENTS_HOME` + `user_skills_dirs`). The fork's entire bundled loader and `superpowers/` package are **deletable**.

**RELOCATE (deploy-time, not in-tree):**
- Copy the 14 translated skill dirs from fork `vibe/core/skills/builtins/superpowers/skills/` → `~/.agents/skills/<skill-name>/SKILL.md` on the target machine. Preserve `superpowers-` prefix + assets. **Requires a deployment/install step** (dotfiles/install script) — bundled-always-present guarantee is gone.

**LEAVE AS-IS (v2.13 already correct):**
- `vibe/core/skills/builtins/__init__.py` — keep upstream `BUILTIN_SKILLS = {skill.name: skill for skill in [VIBE_SKILL]}`. Do NOT add the fork loader.

**DELETE (do not port):**
- `vibe/core/skills/builtins/superpowers/` (entire package + loader).
- `scripts/superpowers/01-tool-names.py`, `scripts/superpowers/02-namespace-and-prose.py` (one-shot tools; keep out of tree, or update hardcoded `ROOT` paths only if retained for future refreshes).

**MODIFY (coordinate with P5):**
- `vibe/core/tools/builtins/skill.py` — add `mutates_state: ClassVar[bool] = False` to `Skill` (L39). **This is a P5 annotation** — land it with P5; if P5 lands first and this is missed, skills get blocked in PLAN (regression).

**MIGRATE TESTS:** `tests/skills/test_builtin_sync.py` (verbatim — `BUILTIN_SKILLS=={'vibe'}` passes after revert), `tests/skills/test_manager.py` (verbatim — already covers `~/.agents/skills` discovery via `TestSkillManagerSearchPaths`), `tests/skills/test_models.py`, `tests/skills/test_parser.py` (verbatim), `tests/tools/test_skill.py` (add `mutates_state=False` assertion once P5 lands).

**Risks:** skill-name collision with new v2.13 built-in commands (audit names vs `superpowers-*`). Deploy-time availability (no in-tree guarantee). `mutates_state` dependency on P5 ordering. `using-superpowers` meta-skill references exact `superpowers-` names — keep verbatim.

---

## Native Replacements — DELETE These

| Fork artifact | v2.13 native replacement | Action |
|---|---|---|
| `vibe/core/skills/builtins/superpowers/` (package + 57-line loader) | `SkillManager._compute_search_paths` + `user_skills_dirs` discovers `~/.agents/skills` | DELETE package; relocate `.md` files to `~/.agents/skills` |
| Fork 3-line edit in `skills/builtins/__init__.py` | upstream one-liner `BUILTIN_SKILLS = {...[VIBE_SKILL]}` | REVERT to upstream |
| `scripts/superpowers/*.py` | n/a (one-shot migration tools) | DO NOT PORT |
| Fork `vibe/core/plan_session.py` copy | upstream `PlanSession` (timestamped path, `read()`, `snapshot_content_hash()`, `has_content_changed()`) | DELETE fork copy; use upstream |
| write_file/search_replace branch of `_PLAN_GATE_BYPASS_TOOLS` | upstream `_plan_overrides()` `permission='never'` + `allowlist=[PLANS_DIR/*]` | TRIM from gate (keep bash/task/mcp) |
| Fork `exit_plan_mode` class scaffolding (BaseTool subclass, AskUserQuestion, formatters) | upstream `exit_plan_mode.py` ships the class | Port run()-body delta ONLY |
| Fork `exit_plan_mode` "only in plan mode" runtime guard as primary gate | upstream `base_disabled` in DEFAULT/ACCEPT_EDITS/AUTO_APPROVE/LEAN | Keep guard as belt-and-suspenders; registration-level disable is free |
| Fork PlanReview UI / live plan-file watch / Ctrl+G | native `PlanReviewRequestedEvent`/`PlanReviewEndedEvent` + `PlanFileMessage` + `action_open_plan_in_editor` | USE NATIVE (in-place path) |
| Fork custom shift+tab PLAN cycle ordering | native `get_agent_order` (DEFAULT→PLAN→ACCEPT_EDITS→AUTO_APPROVE) | USE NATIVE |
| Fork `switch_agent_generation` guard re-add | already present in v2.13 `_cycle_agent` (L2887-2901) | REUSE, do not re-add |
| Fork history re-injection of `reasoning_content` | native `LLMMessage.reasoning_content` + `ReasoningAdapter._convert_assistant_message()` | USE NATIVE (only ThinkTagExtractor is still needed for [THINK] text-tag fallback) |
| Fork manual AutoCompact/`COMPACT` re-port (P5) | native `AutoCompactMiddleware` + `MiddlewareAction.COMPACT` in `_setup_middleware` | USE NATIVE; add only MicroCompact on top |
| Fork `_vibe_home.py` PLANS_DIR change + long comment | v2.13 `_vibe_home.py` already defines `PLANS_DIR = VIBE_HOME.path / 'plans'` | TAKE v2.13 VERBATIM; drop the explanatory comment |
| Fork inline shlex/subprocess editor block (agents-ui edit handler) | native `vibe/cli/textual_ui/external_editor.py` (`ExternalEditor.edit_file()`, `get_editor()`) | DELEGATE to native |
| Fork `_toggle_plan_mode` `asyncio.run()` pattern | native `run_coroutine_threadsafe` template in `_cycle_agent` | REUSE native pattern |
| GrowthBook/experiments custom disable | native double-gate `config.enable_telemetry and config.experiments.enable` in `experiments/session.py` | NO CODE — set config flags |

---

## Uncovered Files — TODO (not in any per-feature spec)

From the coverage audit, these source files carry fork changes that the 11 specs above do **not** explicitly enumerate. Fold each into the indicated phase or open a small companion spec.

**Cluster 1 — Telemetry cleanup (fold into P2 or new `telemetry-turn-summary` spec):**
- `vibe/cli/narrator_manager/narrator_manager.py` — drop `session_metadata_getter`/`_build_metadata`.
- `vibe/cli/turn_summary/tracker.py` — drop `_build_metadata` from the `TurnSummaryTracker` secondary-call path.

**Cluster 2 — Plan-mode dispatch gate (fold into P5):**
- `vibe/core/tools/builtins/{bash,grep,read_file,search_replace,task,todo,webfetch,websearch,write_file,ask_user_question}.py` — `mutates_state: ClassVar[bool]` overrides (already enumerated in P4b STEP 4 / P5; this is the explicit file list).
- `vibe/core/llm/backend/base.py` — add `reasoning_effort` to the backend Protocol.
- `vibe/core/llm/backend/vertex.py` — accept-and-ignore `reasoning_effort`.
- `vibe/core/programmatic.py` — fork-to-dev re-entry loop (programmatic API analog of the acp loop — fold into P4b STEP 7 / P5).
- `vibe/cli/textual_ui/widgets/question_app.py` — PgUp/PgDn scroll for the ExitPlanMode content preview.

**Cluster 3 — reasoning-two-tier companion (fold into P1b):**
- `vibe/cli/textual_ui/handlers/event_handler.py` — `collapsed=False` for `ReasoningMessage` (never auto-collapse reasoning). *(Also the P4a `messages.py` rework touches the streaming/collapse path — coordinate.)*

**Cluster 4 — standalone improvements (open small companion specs / housekeeping):**
- `vibe/core/session/session_logger.py` — **NEW SPEC `session-logger-async-fsync`**: fork offloads `os.fsync` to `asyncio.to_thread`; genuinely custom (v2.13 still blocks). Not from v2.13 — port as a feature.
- `vibe/core/prompts/__init__.py` — `GENERAL_PURPOSE = auto()` `PromptId` enum value (consumed by agents-ui/system_prompt — already noted in P3b; flagged here for completeness).
- `vibe/core/paths/_vibe_home.py` — comment-only fork delta; code is v2.13-identical → **take v2.13 verbatim, drop the comment** (housekeeping).

**All uncovered test files** are companions to the four clusters above (plan-mode dispatch, telemetry cleanup, stats `TurnRecord`, sparse-reminder, inline-tool-call promotion, orphan-trailing-tool repair) — migrate them alongside the corresponding source change, not as standalone gaps.
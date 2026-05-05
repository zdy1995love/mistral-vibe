# Superpowers Integration — Development Plan

Status: planning. Branch: `superpowers`.

## Goal

Make obra/superpowers run end-to-end inside mistral-vibe with the same fidelity as on Claude Code — every skill should be functionally usable, not just textually present. "Perfect" means: a fresh install of mistral-vibe + a one-line setup command yields a working `/style superpowers` experience where all 14 skills (including `subagent-driven-development`) execute without "the agent profile doesn't exist" errors.

## What's already done (migrated to this branch)

1. **Built-in output style** at `vibe/core/prompts/styles/superpowers.md` — the meta-discipline ("1% rule", red-flags table, tool mapping). Activated via `/style superpowers`.
2. **Translation scripts** at `scripts/superpowers/` — replay Claude-Code → mistral-vibe rewrites on a fresh `obra/superpowers` clone. Idempotent.
3. **Vendor tree** at `~/.vibe/vendor/superpowers/` (user-side, not in repo) — `vibe-port` branch with translation commits. Reference layout for users.

## What still needs development

### Phase 1: Built-in agent profiles (the biggest gap)

`subagent-driven-development` and `requesting-code-review` skills dispatch to subagents named `implementer`, `spec-reviewer`, `code-quality-reviewer`, `code-reviewer`. vibe ships only `explore` (read-only). These four need to ship as built-in agent profiles.

**Files to add:**

```
vibe/core/agents/models.py             — extend BuiltinAgentName enum + BUILTIN_AGENTS dict
vibe/core/prompts/implementer.md       — system prompt: implement-per-spec discipline
vibe/core/prompts/spec_reviewer.md     — system prompt: verify code matches spec, nothing more
vibe/core/prompts/code_quality_reviewer.md — system prompt: code smells, duplication, complexity
vibe/core/prompts/code_reviewer.md     — system prompt: general PR review (severity-tagged)
```

**Profile shape (each):**

| profile | enabled_tools | system_prompt_id | safety | agent_type |
|---|---|---|---|---|
| `implementer` | `read_file`, `write_file`, `search_replace`, `bash`, `grep`, `todo`, `task`, `web_search`, `web_fetch` | `implementer` | NEUTRAL | SUBAGENT |
| `spec-reviewer` | `read_file`, `grep`, `bash` (read-only commands), `todo` | `spec_reviewer` | SAFE | SUBAGENT |
| `code-quality-reviewer` | `read_file`, `grep`, `bash` (read-only), `todo` | `code_quality_reviewer` | SAFE | SUBAGENT |
| `code-reviewer` | `read_file`, `grep`, `bash` (read-only), `todo` | `code_reviewer` | SAFE | SUBAGENT |

**Why ship as built-ins (vs. asking users to author them):**
- Users won't author agent profiles. Without these shipped, `subagent-driven-development` is broken-by-default.
- Built-in profiles get tested in CI (snapshot tests for system prompts; load tests).
- Mirrors how `explore` ships today.

**System prompt source material:** the prompt files at `~/.vibe/vendor/superpowers/skills/subagent-driven-development/{implementer,spec-reviewer,code-quality-reviewer}-prompt.md` and `~/.vibe/vendor/superpowers/skills/requesting-code-review/code-reviewer.md`. These are templates with `{PLACEHOLDERS}` — the parent agent fills them in via the `task` tool's `task` arg. The system prompt should be the *non-placeholder* parts (the methodology + role definition), not the templates themselves.

**Tooling allowlist update:**
- Default `tools.task.allowlist` becomes `["explore", "implementer", "spec-reviewer", "code-quality-reviewer", "code-reviewer"]`.
- Exists in `vibe/core/tools/builtins/task.py:53` — change the `Field(default=...)` value.

### Phase 2: Setup command

Goal: one command that takes a fresh user from "vibe installed, no superpowers" to "everything works".

**New CLI subcommand:** `vibe superpowers install` (preferred) or extend `vibe --setup` with a flag.

Steps the command performs:
1. Resolve install dir (default `~/.vibe/vendor/superpowers`).
2. If absent: `git clone https://github.com/obra/superpowers.git <dir>`.
3. If present: `git fetch origin && git checkout -b vibe-port origin/main` (or update existing).
4. Run `python3 scripts/superpowers/01-tool-names.py` against `<dir>/skills/`.
5. Run `python3 scripts/superpowers/02-namespace-and-prose.py` against `<dir>/skills/`.
6. `git -C <dir> commit -am "vibe-port: translate Claude Code names"` (single squashed commit).
7. Patch `~/.vibe/config.toml`:
   - `skill_paths` += `<dir>/skills` (idempotent — check before adding)
   - Optional: prompt user to set `output_style = "superpowers"`
8. Verify: load skills via `SkillManager`, count = 14, no warnings. Print summary.

**Implementation file:** `vibe/cli/commands/superpowers.py` (or under existing `vibe/cli/setup.py` if simpler). Hook into `argparse` in `vibe/cli/entrypoint.py`.

**Uninstall:** `vibe superpowers uninstall` — remove vendor dir, revert config edits using `~/.vibe/config.toml.bak.*` if present.

### Phase 3: Config integration

When the user activates the superpowers experience, two things must be in sync:
- `output_style = "superpowers"` (the discipline)
- `skill_paths` includes the vendor tree (the actual skill bodies)

Currently the user must set both manually. Better: the setup command in Phase 2 handles both. Even better:

**Option A (less invasive):** Setup command writes both to config, user can revert.

**Option B (more magic):** When `output_style = "superpowers"` is loaded, the skill manager scans an extra implicit path `~/.vibe/vendor/superpowers/skills` if it exists. Hidden coupling, but zero-config UX.

**Recommend Option A.** Explicit > magic. Aligns with vibe's existing config style.

### Phase 4: Tests

Add to `tests/`:

```
tests/agents/test_superpowers_agents.py     — load each new profile, verify tool restrictions
tests/prompts/test_superpowers_style.py     — load style, verify content invariants (1% rule present, etc.)
tests/cli/test_superpowers_install.py       — mock-clone + run setup, verify config patched, no double-add
tests/scripts/test_translation_scripts.py   — apply 01+02 to fresh skills/, verify no Claude-name leaks
                                              + idempotence (run twice = same result)
tests/snapshots/                            — snapshot for each new agent's system prompt assembly
```

### Phase 5: Docs

```
README.md                              — add row to Fork Changelog table
docs/superpowers/integration-plan.md   — this file (already exists)
docs/superpowers/usage.md              — user-facing: how to install, activate, customize
docs/superpowers/architecture.md       — dev-facing: how skills load, subagent isolation,
                                          plan-mode fork semantics
CHANGELOG.md                           — under unreleased: superpowers built-in support
```

## Critical files (touch list)

```
[NEW]
vibe/core/agents/models.py:                + 4 BuiltinAgentName entries
                                            + 4 AgentProfile constants  
                                            + dict updates
vibe/core/prompts/implementer.md
vibe/core/prompts/spec_reviewer.md
vibe/core/prompts/code_quality_reviewer.md
vibe/core/prompts/code_reviewer.md
vibe/cli/commands/superpowers.py           — install / uninstall / status
docs/superpowers/usage.md
docs/superpowers/architecture.md
tests/agents/test_superpowers_agents.py
tests/prompts/test_superpowers_style.py
tests/cli/test_superpowers_install.py
tests/scripts/test_translation_scripts.py

[MODIFY]
vibe/core/tools/builtins/task.py           — extend default allowlist
vibe/cli/entrypoint.py                     — register `superpowers` subcommand
README.md                                  — fork changelog row
CHANGELOG.md                               — entry

[ALREADY MIGRATED]
vibe/core/prompts/styles/superpowers.md    — output style (in this branch)
scripts/superpowers/{01-tool-names.py,02-namespace-and-prose.py,README.md}
```

## Open architectural decisions

These need user input before implementing:

### D1. Vendor as submodule, or fetch on install?

- **Submodule** (`mistral-vibe/vendor/superpowers/`): bundles fixed version with each release; reproducible; bumps require PR. License: MIT + Apache mix — compatible with vibe's MIT.
- **Fetch on install** (current plan): vendor tree lives under `~/.vibe/vendor/`, install command clones. Pros: no repo bloat, users get latest. Cons: install requires network; CI testing harder.

Recommendation: **fetch on install.** Keeps the repo small, lets users pin or follow upstream as they choose. Tests can use a fixture skills tree.

### D2. Custom agent system prompts — derive from upstream templates or write fresh?

- **Derive**: copy non-placeholder text from `subagent-driven-development/*-prompt.md`. Faster, mirrors upstream. Risk: upstream changes don't propagate to our system prompts.
- **Write fresh**: author shorter vibe-native system prompts. More work, but tighter and stays consistent with vibe's existing prompt style.

Recommendation: **derive for v1, refactor later.** Get parity first; clean up after we see it work.

### D3. `task` tool allowlist — expand defaults or require user opt-in?

Currently allowlist default is `["explore"]`. Adding the four new agents means they get `permission=ALWAYS` (no prompt) by default. Some users may want approval for `implementer` (it can write code).

Recommendation: **default to `["explore", "spec-reviewer", "code-quality-reviewer", "code-reviewer"]` (read-only) and leave `implementer` at `permission=ASK`.** Implementer modifies code → it's the same trust level as raw `bash`/`write_file`, which already prompt.

### D4. Slash command for install vs. CLI subcommand?

- **Slash** (`/superpowers-install` from inside vibe): convenient, but slash-commands are skills and shouldn't make config changes.
- **CLI subcommand** (`vibe superpowers install`): cleaner. Matches `vibe --setup`.

Recommendation: **CLI subcommand.**

## Execution order

```
sprint 1 (foundation)
├── 1.1 ship 4 built-in agent profiles + system prompts
├── 1.2 update task.py default allowlist (D3 split: read-only auto, implementer ask)
├── 1.3 tests for agent loading + tool restrictions
└── 1.4 commit on `superpowers` branch

sprint 2 (UX)
├── 2.1 implement `vibe superpowers install` subcommand
├── 2.2 implement uninstall + status
├── 2.3 tests with mocked git/filesystem
└── 2.4 commit

sprint 3 (docs + polish)
├── 3.1 author docs/superpowers/usage.md + architecture.md
├── 3.2 README fork-changelog row + CHANGELOG entry
├── 3.3 snapshot tests for system prompts
└── 3.4 commit + open PR to dev (or main, per fork policy)
```

## Verification (definition of done)

A fresh checkout of `superpowers` branch passes all of:

```bash
# 1. clean install
rm -rf ~/.vibe/vendor/superpowers
vibe superpowers install
# expects: skills cloned, translated, config patched, "14 skills loaded" message

# 2. activate style
vibe -p "/style superpowers" --output text
# expects: style switched, persisted

# 3. run a real workflow without errors — explore-only path
vibe -p "use brainstorming skill to plan a hello-world feature" --max-turns 5
# expects: model calls skill tool with name=brainstorming, runs the flow

# 4. dispatch implementer subagent (the new built-in)
vibe -p "use subagent-driven-development to add a function returning 42" --max-turns 8
# expects: model dispatches `task` with agent=implementer, subagent writes code, returns

# 5. parallel dispatch
vibe -p "use dispatching-parallel-agents to investigate 3 unrelated files" --max-turns 6
# expects: 3 concurrent task calls, results returned in any order

# 6. clean uninstall
vibe superpowers uninstall
# expects: vendor dir removed, config restored, skills disappear from menu

# 7. test suite
uv run pytest tests/ -k superpowers
# expects: green
```

## Out of scope (deferred)

- Visual companion (Node-based browser UI in `brainstorming/visual-companion.md`) — not porting; vibe TUI has no equivalent.
- `bash` `run_in_background` parameter — no equivalent in vibe; visual companion is the only consumer and it's deferred.
- Plugin marketplace integration — vibe has no marketplace yet; "install via plugin manager" requires building that infrastructure first.
- Hooks (`hooks/` in upstream superpowers, Claude Code hook format) — vibe's hook system differs; SessionStart auto-load is replaced by output style activation.

## Risk register

| Risk | Mitigation |
|---|---|
| Upstream superpowers refactor breaks translation scripts | Translation scripts use surgical regex; idempotence test catches drift. CI runs install against latest `obra/superpowers main`. |
| Built-in agent system prompts go stale relative to upstream prompt templates | Add upstream-template-diff check in CI (warn, don't fail). Re-derive on each minor superpowers release. |
| `implementer` agent escapes its read scope due to misconfigured tool list | Snapshot test of effective tool list per profile. Permission set is the source of truth. |
| User has existing `~/.vibe/config.toml` with `output_style` already set | Setup command shows diff before write, asks confirmation, backs up to `.bak.<timestamp>`. |
| Vendor dir gets out of sync with translation scripts | `vibe superpowers status` reports drift; `vibe superpowers install` is idempotent so re-runs heal state. |

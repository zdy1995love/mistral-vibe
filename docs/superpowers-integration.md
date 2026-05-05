# Superpowers Integration — Development Plan

Status: planning. Branch: `superpowers`.

## Goal

Make obra/superpowers run end-to-end inside mistral-vibe with the same fidelity as on Claude Code — every skill should be functionally usable, not just textually present. "Perfect" means: a fresh install of mistral-vibe + a one-line setup yields a working `/style superpowers` experience where all 14 skills (including `subagent-driven-development`) execute without "the agent profile doesn't exist" errors.

## Reference reading

Before iterating on this plan, the following references shaped its design:

- **Claude Code's built-in agents** (`~/LCD_Module_code/claude-code-2/src/tools/AgentTool/built-in/`): CC ships 6 — `general-purpose`, `Explore`, `Plan`, `verification`, `claude-code-guide`, `statusline-setup`. Critically, **CC does NOT ship `implementer` / `spec-reviewer` / `code-quality-reviewer` / `code-reviewer`** as built-in agent types. Those names appear in superpowers skill bodies but the actual `Task` calls dispatch to `general-purpose` and pass the role-specific prompt template as the task argument.

- **Qwen Code's built-in subagents** (`~/qwen-code/packages/core/src/subagents/builtin-agents.ts`): qwen ships 3 — `general-purpose`, `Explore`, `statusline-setup`. Same conclusion: no role-specific implementer/reviewer agents.

- **`obra/superpowers/.claude-plugin/plugin.json`**: the superpowers plugin itself **provides only skills, not agents**. There is no agent registry in the plugin.

The role identity in `subagent-driven-development` ("implementer", "spec-reviewer", etc.) is conveyed by the **prompt template content** (e.g., `subagent-driven-development/implementer-prompt.md`), not by a dedicated agent profile. The parent dispatches with `agent=general-purpose` and stuffs the template into the `task` arg.

## What's already done (migrated to this branch)

1. **Built-in output style** at `vibe/core/prompts/styles/superpowers.md` — meta-discipline (1% rule, red-flags table, vibe tool mapping).
2. **Translation scripts** at `scripts/superpowers/` — idempotent rewrites for a fresh `obra/superpowers` clone.
3. **Vendor tree** at `~/.vibe/vendor/superpowers/` (user-side, `vibe-port` branch with translation commits).

## What still needs development

### Sprint 1: ship `general-purpose` built-in agent (the only blocker)

**This is the entire functional fix for `subagent-driven-development`.** vibe currently ships only `explore` (read-only). Adding `general-purpose` (full tools) lets superpowers' subagent-driven workflow run — exactly how it runs on CC and qwen.

**Files to add/modify:**

```
vibe/core/agents/models.py
  + BuiltinAgentName.GENERAL_PURPOSE = "general-purpose"
  + GENERAL_PURPOSE = AgentProfile(...)  ← all tools, system_prompt_id="general_purpose"
  + BUILTIN_AGENTS[GENERAL_PURPOSE] = GENERAL_PURPOSE
  + builtin_order list update

vibe/core/prompts/general_purpose.md      [NEW]
  ← system prompt, derived from CC's generalPurposeAgent.ts
```

**Profile shape:**

```python
GENERAL_PURPOSE = AgentProfile(
    name=BuiltinAgentName.GENERAL_PURPOSE,
    display_name="General-Purpose",
    description=(
        "General-purpose subagent for complex multi-step tasks: research, "
        "code search, implementation, mixed read+write work."
    ),
    safety=AgentSafety.NEUTRAL,
    agent_type=AgentType.SUBAGENT,
    overrides={
        # No enabled_tools restriction → inherits parent config's enabled_tools
        # (typically all builtins). Matches CC's `tools: ['*']`.
        "system_prompt_id": "general_purpose",
    },
)
```

**System prompt source (port from CC, vibe-flavored):** see `~/LCD_Module_code/claude-code-2/src/tools/AgentTool/built-in/generalPurposeAgent.ts`. Adapt: replace "Claude Code" branding, drop CC-specific tool names, keep the strengths/guidelines list.

**Task tool allowlist:** keep default `["explore"]`. `general-purpose` can write code → auto-approve is risky. Default `permission=ASK` is correct. Users add to personal allowlist if they trust the workflow.

That's all of Sprint 1. ~50 lines of code + one prompt file.

### Sprint 2: clarify skill bodies (prompt templates ≠ agent types)

Skill bodies currently say "dispatch implementer subagent". The model could mistakenly set `agent="implementer"` (which doesn't exist). Make the agent-vs-template distinction explicit.

**Files to edit on `vibe-port` branch:**
```
subagent-driven-development/SKILL.md  — explain "implementer"/"spec-reviewer"/
                                         "code-quality-reviewer" are PROMPT TEMPLATES
                                         in this directory; the task tool dispatches
                                         agent="general-purpose" and passes the
                                         template content as the task argument.
requesting-code-review/SKILL.md       — same: code-reviewer.md is a template, not an agent.
```

Add a third pass `scripts/superpowers/03-template-vs-agent.py` so this is replayable on rebase.

After Sprints 1 + 2, **all 14 skills run end-to-end** without user-defined agents.

### Sprint 3: optional `verification` agent

CC ships a `verification` agent (adversarial PASS/FAIL/PARTIAL verifier with strict output format). Useful for `verification-before-completion` when the user wants delegated verification. Not blocking — the skill works fine inline — but a quality-of-life win.

Port from `~/LCD_Module_code/claude-code-2/src/tools/AgentTool/built-in/verificationAgent.ts`. Adapt tool restrictions (block `write_file`/`search_replace`/mutating `bash`; allow `/tmp`).

### Sprint 4: `vibe superpowers install` CLI

One command takes a fresh user from "vibe installed, no superpowers" to "everything works".

**New CLI subcommand:** `vibe superpowers install` (also `uninstall` / `status`).

Steps:
1. Resolve install dir (default `~/.vibe/vendor/superpowers`).
2. If absent: `git clone https://github.com/obra/superpowers.git <dir>`.
   If present: `git fetch origin && git rebase origin/main vibe-port`.
3. Run `python3 scripts/superpowers/01-tool-names.py` → `02-namespace-and-prose.py` → `03-template-vs-agent.py`.
4. `git -C <dir> commit -am "vibe-port: translation"` on `vibe-port` branch.
5. Patch `~/.vibe/config.toml` (idempotent, with `.bak.<ts>` backup):
   - `skill_paths` += `<dir>/skills`
   - Optionally prompt: set `output_style = "superpowers"`?
6. Verify: load skills via `SkillManager`; expect 14 + 1 builtin; print summary.

**Implementation file:** `vibe/cli/commands/superpowers.py`. Hook into argparse in `vibe/cli/entrypoint.py`.

### Sprint 5: tests + docs

```
tests/agents/test_general_purpose_agent.py       — load profile, verify all-tools access
tests/prompts/test_superpowers_style.py          — load style, invariants (1% rule etc.)
tests/cli/test_superpowers_install.py            — mocked git + filesystem
tests/scripts/test_translation_scripts.py        — apply 01..03 idempotence
docs/superpowers-usage.md                         — user guide
docs/superpowers-architecture.md                  — dev internals
README.md                                         — fork-changelog row
CHANGELOG.md                                      — entry
```

## Critical files (touch list — final)

```
[ALREADY MIGRATED]
vibe/core/prompts/styles/superpowers.md
scripts/superpowers/{01-tool-names,02-namespace-and-prose}.py
scripts/superpowers/README.md
docs/superpowers-integration.md   ← this file

[NEW — Sprint 1]
vibe/core/prompts/general_purpose.md

[NEW — Sprint 3 (optional)]
vibe/core/prompts/verification.md

[NEW — Sprint 4]
vibe/cli/commands/superpowers.py
scripts/superpowers/03-template-vs-agent.py    (also edits vibe-port branch)

[NEW — Sprint 5]
tests/agents/test_general_purpose_agent.py
tests/prompts/test_superpowers_style.py
tests/cli/test_superpowers_install.py
tests/scripts/test_translation_scripts.py
docs/superpowers-usage.md
docs/superpowers-architecture.md

[MODIFY]
vibe/core/agents/models.py          — register general-purpose (+ verification)
vibe/cli/entrypoint.py              — register `superpowers` subcommand
README.md                            — fork-changelog row
CHANGELOG.md                         — entry
```

## Open architectural decisions

### D1. Vendor as submodule, or fetch on install? — **fetch on install**

`mistral-vibe/vendor/superpowers/` as a git submodule bundles a fixed version. License (MIT) is compatible. But it adds repo bloat and tight coupling to upstream. Better: install command clones to `~/.vibe/vendor/`; users follow upstream at their own pace.

### D2. `verification` agent — port from CC or skip? — **defer (Sprint 3)**

`verification-before-completion` works inline; the verification agent is a delegated alternative. Useful but not blocking. Land Sprints 1–2 first; revisit demand.

### D3. Slash command for install vs. CLI subcommand? — **CLI subcommand**

Slash commands are skills — they shouldn't make config changes. Matches `vibe --setup` UX precedent.

### D4. Update `tools.task.allowlist` default? — **no, keep `["explore"]`**

`general-purpose` can write code → adding it auto-approved is risky. Default `permission=ASK` is correct.

## Execution order

```
Sprint 1 (foundation — 1 hour)
├── 1.1 add BuiltinAgentName.GENERAL_PURPOSE + AgentProfile
├── 1.2 author vibe/core/prompts/general_purpose.md
├── 1.3 single test: load profile, verify dispatch from `task` tool works
└── 1.4 commit on `superpowers` branch

Sprint 2 (skill body clarity — 30 min)
├── 2.1 author scripts/superpowers/03-template-vs-agent.py
├── 2.2 update vibe-port branch on user vendor tree
└── 2.3 commit script on `superpowers` branch

Sprint 3 (verification agent — 1 hour, optional)
├── 3.1 port verificationAgent.ts → AgentProfile + prompt
├── 3.2 tests
└── 3.3 commit

Sprint 4 (install CLI — 2-3 hours)
├── 4.1 implement install / uninstall / status
├── 4.2 mock-fs tests
└── 4.3 commit

Sprint 5 (docs + polish — 1 hour)
├── 5.1 user / architecture docs
├── 5.2 README + CHANGELOG entries
├── 5.3 final tests
└── 5.4 PR to dev (or main, per fork policy)
```

Total estimate: 5–7 hours of focused work. **Sprint 1 alone unblocks `subagent-driven-development`.**

## Verification (definition of done)

A fresh checkout of the `superpowers` branch passes all of:

```bash
# 1. clean install
rm -rf ~/.vibe/vendor/superpowers
vibe superpowers install
# expects: skills cloned, translated, config patched, "14 skills loaded"

# 2. activate style
vibe -p "/style superpowers" --output text

# 3. inline workflow (no subagents)
vibe -p "use brainstorming skill to plan a hello-world feature" --max-turns 5

# 4. THE big one: subagent-driven-development end-to-end
vibe -p "use subagent-driven-development to add a function that returns 42" --max-turns 8
# expects: model dispatches `task` with agent=general-purpose, passes
#          implementer-prompt.md template content as task arg, subagent
#          writes code, parent dispatches review subagents, returns

# 5. parallel dispatch
vibe -p "use dispatching-parallel-agents to investigate 3 unrelated files" --max-turns 6

# 6. clean uninstall
vibe superpowers uninstall

# 7. test suite
uv run pytest tests/ -k superpowers
```

## Out of scope (deferred indefinitely)

- Visual companion (Node-based browser UI in `brainstorming/visual-companion.md`)
- `bash` `run_in_background` parameter (only consumer is visual companion)
- Plugin marketplace integration (vibe has no marketplace yet)
- `claude-code-guide` agent port (CC-specific, not relevant)
- Hooks (Claude Code hook format) — vibe has its own hook system
- Implicit-fork subagent (qwen's design) — advanced, not required for superpowers
- Role-specific built-in agents (`implementer`, `spec-reviewer`, etc.) — **abandoned**: not how CC or qwen do it; superpowers itself doesn't ship these. Roles are conveyed via prompt templates passed to `general-purpose`.

## Risk register

| Risk | Mitigation |
|---|---|
| Upstream superpowers refactor breaks translation scripts | Idempotent scripts; CI test against latest `obra/superpowers main`. |
| Skill body still says "implementer subagent" and model dispatches `agent="implementer"` (404) | Sprint 2 explicit clarification + post-translate audit grep. |
| `general-purpose` system prompt drifts from CC's | Re-derive from CC's source on each minor superpowers release. |
| User has existing `~/.vibe/config.toml` with conflicting settings | Install command shows diff, asks confirmation, backs up to `.bak.<ts>`. |
| Vendor dir gets out of sync with translation scripts | Idempotent install; `vibe superpowers status` reports drift. |

Anchors confirmed and align with the spec's line references (within drift tolerance). The branch is `feat/port-2.13` rather than `integration/upstream-v2.9.6`, but the file structure matches the specs. I have enough verified context to synthesize the plan. The spec is self-contained and the anchors check out.

````markdown
# P5b — Plan Mode Fork-to-Dev: APPLY-READY Execution Script

Target tree: `/home/zdy/mistral-vibe-2.13` (verified on branch `feat/port-2.13`; all spec anchors confirmed against working tree). Apply steps **top-to-bottom**. Each step is independently compilable except where a hard runtime dependency is called out; the ordering below guarantees that every referenced symbol exists before the code that calls it.

---

## 0. Dependency graph (what must land before what)

```
STEP 1  base.py        : InvokeContext.request_fork_to_dev_callback + BaseTool.mutates_state  ── pure additive, no deps
STEP 2  builtins/*.py  : mutates_state ClassVar on 13 existing tools                            ── needs STEP 1 (BaseTool default)
STEP 3  manager.py     : pre_plan_profile stash/property                                        ── no deps
STEP 4  models.py      : GENERAL_PURPOSE, _PLAN_BASH_…, _NON_PLAN_BASE_DISABLED, _plan_overrides ── no deps (enter_plan_mode name is inert no-op until STEP 6)
STEP 5  prompts/       : SystemPrompt.GENERAL_PURPOSE + general_purpose.md                        ── no deps (paired with STEP 4)
STEP 6  enter_plan_mode.py (CREATE) + acp NON_INTERACTIVE list                                    ── needs STEP 1 (mutates_state), STEP 4 (BUILTIN_AGENTS/base_disabled)
STEP 7  exit_plan_mode.py delta (run-body rewrite)                                                ── needs STEP 1 (request_fork_to_dev_callback) + STEP 3 (pre_plan_profile)
STEP 8  middleware.py + agent_loop import (sparse reminder)                                       ── no deps
STEP 9  agent_loop.py  : gate + fork-to-dev API + plan-modified detect + event suppression       ── needs STEP 1,3,4,8 (callback field, pre_plan_profile, mutates_state, sparse import)
STEP 10 app.py + commands.py + plan_mode_indicator.py + app.tcss + acp drivers (UI/drivers)       ── needs STEP 3 (pre_plan_profile) + STEP 9 (pending_fork_to_dev / fork_to_dev)
```

**Critical sequencing rules**
1. STEP 1 (callback field + `mutates_state` default) is the root — nothing referencing `ctx.request_fork_to_dev_callback` or `tool.mutates_state` runs before it.
2. STEP 3 (`pre_plan_profile`) before STEP 7 and STEP 9 and STEP 10 — all three read it.
3. STEP 4/5 (models + prompts) before STEP 6 (enter_plan_mode registration relies on `BUILTIN_AGENTS`/`base_disabled`); but the `enter_plan_mode` *name* added to `base_disabled` in STEP 4 is a harmless no-op before the tool exists, so STEP 4 may land first safely.
4. STEP 9 (agent_loop) is the integration point — it MUST come after 1/3/4/8.
5. STEP 10 (drivers/UI) is the consumer of `pending_fork_to_dev`/`fork_to_dev`/`pre_plan_profile` — land it LAST.

**`_plan_overrides` write-coordination:** STEP 4 is the *only* writer of the `base_disabled` key inside `_plan_overrides()`. Do not let STEP 6 also patch `_plan_overrides()` — STEP 6 touches only `enter_plan_mode.py`, the acp constant, and (per spec) is registered via auto-discovery. Single writer = no merge conflict.

---

## STEP 1 — `vibe/core/tools/base.py` (foundation: callback field + mutates_state default)

**1a. InvokeContext field** — anchor: lines 55-56 (`switch_agent_callback` then `skill_manager`). `Callable` already imported (line 4), `Path` already imported (line 9). No import change.

OLD:
```python
    switch_agent_callback: SwitchAgentCallback | None = field(default=None)
    skill_manager: SkillManager | None = field(default=None)
```
NEW:
```python
    switch_agent_callback: SwitchAgentCallback | None = field(default=None)
    # Stage a fork-to-dev: the host app reads it after the current act()
    # returns, wipes context, and re-enters act() with the seed message.
    # Signature: (plan_text, plan_path, target_profile) -> None.
    request_fork_to_dev_callback: Callable[[str, Path, str], None] | None = field(
        default=None
    )
    skill_manager: SkillManager | None = field(default=None)
```

**1b. BaseTool.mutates_state default** — anchor: `description` ClassVar followed by `prompt_path: ClassVar[Path] | None = None`.

OLD:
```python
    prompt_path: ClassVar[Path] | None = None
```
NEW (insert the comment+attr *before* `prompt_path`):
```python
    # Plan mode gate: True means the tool can mutate filesystem / shell / network
    # state and must be blocked while plan mode is active. Read-only tools
    # explicitly override to False. New tools default to True (safe side) so
    # forgetting to declare doesn't accidentally widen plan mode.
    mutates_state: ClassVar[bool] = True

    prompt_path: ClassVar[Path] | None = None
```

---

## STEP 2 — `mutates_state` ClassVar on the 13 existing builtins

Each edit appends one line directly after the `description` ClassVar closing line. (Default is `True`, so the `=True` ones are belt-and-suspenders but kept for metadata completeness per the locked decision.)

| File | Append after `description` ClassVar | Value |
|---|---|---|
| `builtins/bash.py` | `    mutates_state: ClassVar[bool] = True` | True |
| `builtins/task.py` | `    mutates_state: ClassVar[bool] = True` | True |
| `builtins/search_replace.py` | `    mutates_state: ClassVar[bool] = True` | True (native `_plan_overrides` still does the real enforcement) |
| `builtins/write_file.py` | `    mutates_state: ClassVar[bool] = True` | True (native `_plan_overrides` still does the real enforcement) |
| `builtins/ask_user_question.py` | `    mutates_state: ClassVar[bool] = False` | False |
| `builtins/exit_plan_mode.py` | (handled in STEP 7, paired with run-body rewrite) | False |
| `builtins/grep.py` | `    mutates_state: ClassVar[bool] = False` | False |
| `builtins/read_file.py` | `    mutates_state: ClassVar[bool] = False` | False |
| `builtins/skill.py` | `    mutates_state: ClassVar[bool] = False` | False |
| `builtins/todo.py` | `    mutates_state: ClassVar[bool] = False` | False (in-memory TodoState only) |
| `builtins/webfetch.py` | `    mutates_state: ClassVar[bool] = False` | False |
| `builtins/websearch.py` | `    mutates_state: ClassVar[bool] = False` | False |

For each: read the `description = (...)` block, then `Edit` to insert the `mutates_state` line immediately after the closing `)` (or after the single-line string). Exact OLD/NEW per the spec's per-file `change` blocks. `exit_plan_mode.py` is deliberately deferred to STEP 7 (same file gets the run-body rewrite). `enter_plan_mode.py` is created in STEP 6 with `mutates_state=False` already inline.

**Verify STEP 1+2:**
```bash
python -c "from vibe.core.tools.base import BaseTool; import inspect; from dataclasses import fields; from vibe.core.tools.base import InvokeContext; assert BaseTool.mutates_state is True; assert 'request_fork_to_dev_callback' in {f.name for f in fields(InvokeContext)}"
python -c "from vibe.core.tools.builtins.bash import Bash; from vibe.core.tools.builtins.task import Task; from vibe.core.tools.builtins.search_replace import SearchReplace; from vibe.core.tools.builtins.write_file import WriteFile; assert all(t.mutates_state is True for t in [Bash,Task,SearchReplace,WriteFile])"
python -c "from vibe.core.tools.builtins.ask_user_question import AskUserQuestion; from vibe.core.tools.builtins.grep import Grep; from vibe.core.tools.builtins.read_file import ReadFile; from vibe.core.tools.builtins.skill import Skill; from vibe.core.tools.builtins.todo import Todo; from vibe.core.tools.builtins.webfetch import WebFetch; from vibe.core.tools.builtins.websearch import WebSearch; assert all(t.mutates_state is False for t in [AskUserQuestion,Grep,ReadFile,Skill,Todo,WebFetch,WebSearch])"
```
(The spec's `inspect.fields` is wrong — use `dataclasses.fields` as above.)

---

## STEP 3 — `vibe/core/agents/manager.py` (pre_plan_profile stash)

**3a. `__init__` slot** — anchor: line 59 `self._cached_config: VibeConfig | None = None` then line 60 `self._runtime_registered: set[str] = set()`.

OLD:
```python
        self._cached_config: VibeConfig | None = None
        self._runtime_registered: set[str] = set()
```
NEW:
```python
        self._cached_config: VibeConfig | None = None
        # Profile name that was active at the moment we entered PLAN mode, so
        # cancel/exit can restore it instead of always defaulting to DEFAULT.
        # Set by switch_profile when transitioning into PLAN; cleared on any
        # transition away from PLAN.
        self._pre_plan_profile: str | None = None
        self._runtime_registered: set[str] = set()
```

**3b. property + switch_profile rewrite** — anchor: `def switch_profile(self, name: str)` at line 94.

OLD:
```python
    def switch_profile(self, name: str) -> None:
        self.active_profile = self.get_agent(name)
        self._cached_config = None
```
NEW:
```python
    @property
    def pre_plan_profile(self) -> str | None:
        return self._pre_plan_profile

    def switch_profile(self, name: str) -> None:
        current = self.active_profile.name
        if name == BuiltinAgentName.PLAN and current != BuiltinAgentName.PLAN:
            # Stash the entry-point profile so /plan cancel and ExitPlanMode
            # can restore it.
            self._pre_plan_profile = current
        elif name != BuiltinAgentName.PLAN:
            # Any non-PLAN destination clears the stash, including transitions
            # between non-plan profiles via the cycle key.
            self._pre_plan_profile = None
        self.active_profile = self.get_agent(name)
        self._cached_config = None
```
Confirm `BuiltinAgentName` is imported in manager.py; if not, add `from vibe.core.agents.models import BuiltinAgentName`.

**Verify:**
```bash
python -c "
from vibe.core.agents.manager import AgentManager
# instantiate per existing test fixtures; then:
# m.switch_profile('plan'); assert m.pre_plan_profile=='default'
# m.switch_profile('default'); assert m.pre_plan_profile is None
print('manager ok')"
```

---

## STEP 4 — `vibe/core/agents/models.py` (GENERAL_PURPOSE + plan constants + _plan_overrides)

Apply edits in this order:

**4a. Enum member** — anchor: `EXPLORE = "explore"` / `LEAN = "lean"`.
```
    EXPLORE = "explore"
    GENERAL_PURPOSE = "general-purpose"
    LEAN = "lean"
```

**4b. `_PLAN_BASH_READ_ONLY_ALLOWLIST`** — insert between `CHAT_AGENT_TOOLS = [...]` and `def _plan_overrides()` (≈ line 100). Copy the fork's full block verbatim:
```bash
git -C /home/zdy/mistral-vibe show integration/upstream-v2.9.6:vibe/core/agents/models.py
```
Extract the comment + the read-only command-prefix list (`ls find tree cat head tail less more file stat wc du df grep egrep fgrep rg ag pwd which whereis type basename dirname realpath echo date whoami uname hostname uptime ps pgrep lsof id groups env printenv "git status" "git log" "git diff" "git show" "git branch" "git tag" "git remote" "git rev-parse" "git ls-files" "git blame" "git config --get"`).

**4c. `_plan_overrides()` body** — anchor: line 100-110 returning `{"tools": {"write_file": {...}, "search_replace": {...}}}`. **Keep `never`** (locked decision — do NOT flip to `ask`). Only add the `bash` allowlist and `base_disabled`.

OLD:
```python
    return {
        "tools": {
            "write_file": {"permission": "never", "allowlist": [plans_pattern]},
            "search_replace": {"permission": "never", "allowlist": [plans_pattern]},
        }
    }
```
NEW:
```python
    return {
        # write_file / search_replace stay at 'never' + plans allowlist:
        # resolve_path_permission returns ALWAYS on a plans-dir match (so the
        # plan file authors), and the dispatch gate (agent_loop) only passes
        # mutating tools whose resolve_permission yields ALWAYS. 'never' keeps a
        # hard-deny backstop for non-plans writes. We do NOT switch to 'ask'.
        # bash: read-only allowlist lets exploratory ls/find/grep/git-log
        # through (resolve_permission -> ALWAYS on full match); anything else is
        # blocked by the dispatch gate.
        "tools": {
            "write_file": {"permission": "never", "allowlist": [plans_pattern]},
            "search_replace": {"permission": "never", "allowlist": [plans_pattern]},
            "bash": {"permission": "ask", "allowlist": _PLAN_BASH_READ_ONLY_ALLOWLIST},
        },
        # Hide the entry tool while already in plan; ExitPlanMode is the way out.
        "base_disabled": ["enter_plan_mode"],
    }
```

**4d. `_NON_PLAN_BASE_DISABLED` constant** — insert immediately before `DEFAULT = AgentProfile(`:
```python
# Hide both plan-mode tools from LLM tool list in non-PLAN profiles.
# - exit_plan_mode is unusable outside PLAN (it errors).
# - enter_plan_mode was usable but was observed to degrade tool-call
#   reliability on some models (Mistral-Small-4 with vLLM, the model
#   started narrating bash commands in markdown instead of calling them).
#   Plan-mode entry stays available to users via the /plan slash command
#   and shift+tab cycle; LLM-driven entry from non-PLAN profiles is
#   removed as the cost outweighed the benefit.
_NON_PLAN_BASE_DISABLED = ["exit_plan_mode", "enter_plan_mode"]
```

**4e. Profile base_disabled rewrites** (verified line refs from grep: 115, 137, 149, 197):
- DEFAULT (L115): `overrides={"base_disabled": ["exit_plan_mode"]}` → `overrides={"base_disabled": _NON_PLAN_BASE_DISABLED}`
- ACCEPT_EDITS (L137): `"base_disabled": ["exit_plan_mode"],` → `"base_disabled": _NON_PLAN_BASE_DISABLED,`
- AUTO_APPROVE (L149): `overrides={"bypass_tool_permissions": True, "base_disabled": ["exit_plan_mode"]},` → multiline:
  ```python
  overrides={
      "bypass_tool_permissions": True,
      "base_disabled": _NON_PLAN_BASE_DISABLED,
  },
  ```
- LEAN (L197): `"base_disabled": ["exit_plan_mode"],` → (inline list with rationale comment):
  ```python
      # Disable both plan-mode round-trip tools: the LEAN profile is a
      # specialized model+prompt setup, and letting the LLM call
      # enter_plan_mode would silently switch to the PLAN profile and lose
      # the LEAN system prompt and model selection.
      "base_disabled": ["exit_plan_mode", "enter_plan_mode"],
  ```

**4f. GENERAL_PURPOSE profile** — insert after the `EXPLORE = AgentProfile(...)` block, before `LEAN = AgentProfile(`:
```python
GENERAL_PURPOSE = AgentProfile(
    name=BuiltinAgentName.GENERAL_PURPOSE,
    display_name="General-Purpose",
    description=(
        "General-purpose subagent for complex multi-step tasks: research, "
        "code search, implementation, and mixed read/write work. Used by "
        "superpowers' subagent-driven workflow when the parent passes a "
        "role-defining prompt template (implementer, code-reviewer, etc.)."
    ),
    safety=AgentSafety.NEUTRAL,
    agent_type=AgentType.SUBAGENT,
    # No `enabled_tools` restriction -> inherits parent's tool set (effectively
    # all builtins). Mirrors Claude Code's `tools: ['*']` for general-purpose.
    overrides={"system_prompt_id": "general_purpose"},
)
```
Confirm `AgentSafety`, `AgentType` are already imported/defined in models.py (they are — `safety` at L53).

**4g. BUILTIN_AGENTS registration**:
```
    BuiltinAgentName.EXPLORE: EXPLORE,
    BuiltinAgentName.GENERAL_PURPOSE: GENERAL_PURPOSE,
    BuiltinAgentName.LEAN: LEAN,
```

---

## STEP 5 — `vibe/core/prompts/` (GENERAL_PURPOSE prompt)

**5a. Enum member** — anchor: `LEAN = auto()` / `MINIMAL = auto()` (verified L27/L28). Do NOT drop MINIMAL.
```
    LEAN = auto()
    GENERAL_PURPOSE = auto()
    MINIMAL = auto()
```

**5b. CREATE `vibe/core/prompts/general_purpose.md`** — verbatim copy:
```bash
git -C /home/zdy/mistral-vibe show integration/upstream-v2.9.6:vibe/core/prompts/general_purpose.md > /home/zdy/mistral-vibe-2.13/vibe/core/prompts/general_purpose.md
```
Begins `You are a subagent for **mistral-vibe**...`, ends `...The role identity comes from the template, not from your agent type.`

**Verify STEP 4+5:**
```bash
python -c "from vibe.core.agents.models import BUILTIN_AGENTS, GENERAL_PURPOSE, _PLAN_BASH_READ_ONLY_ALLOWLIST, _NON_PLAN_BASE_DISABLED, _plan_overrides; assert 'general-purpose' in BUILTIN_AGENTS; po=_plan_overrides(); assert po['tools']['write_file']['permission']=='never'; assert 'bash' in po['tools']; assert po['base_disabled']==['enter_plan_mode']"
python -c "from vibe.core.prompts import load_system_prompt; t=load_system_prompt('general_purpose'); assert 'subagent for' in t.lower()"
```

---

## STEP 6 — CREATE `enter_plan_mode` tool + acp suppression

**6a. CREATE `vibe/core/tools/builtins/enter_plan_mode.py`** — drop-in mirror of `exit_plan_mode.py` structure. Source it from the fork and adapt:
```bash
git -C /home/zdy/mistral-vibe show integration/upstream-v2.9.6:vibe/core/tools/builtins/enter_plan_mode.py
```
Required invariants in the ported file:
- `mutates_state: ClassVar[bool] = False`.
- **Polarity:** guards on `active_profile.name != PLAN` (enabled outside plan); errors when `== PLAN` ("already in plan mode").
- Errors without `agent_manager` (match `"agent manager"`), errors without `user_input_callback` (match `"interactive UI"`).
- AskUserQuestion confirmation **retained** (anti-hallucination).
- Switch path prefers `ctx.switch_agent_callback(BuiltinAgentName.PLAN)`, falls back to `ctx.agent_manager.switch_profile(BuiltinAgentName.PLAN)`.
- Answer comparison lowercased: `answer.answer.lower() == "yes, enter plan mode"`.
- All imports (`BaseTool`, `BaseToolConfig`, `BaseToolState`, `InvokeContext`, `ToolError`, `ToolPermission`, `AskUserQuestionArgs/Result`, `Choice`, `Question`, `ToolCallDisplay`, `ToolResultDisplay`, `ToolUIData`, `BuiltinAgentName`) resolve at the same v2.13 paths used by `exit_plan_mode.py`.
- File name has **no leading underscore** (auto-discovery requirement).

**6b. CREATE `tests/tools/test_enter_plan_mode.py`** (alongside `test_exit_plan_mode.py`; import `from tests.mock.utils import collect_result`). Eight cases (see Test Plan).

**6c. `vibe/acp/acp_agent_loop.py`** — anchor: `NON_INTERACTIVE_DISABLED_TOOLS = ["ask_user_question", "exit_plan_mode"]` (module-level constant; covers all 3 call sites).
```python
NON_INTERACTIVE_DISABLED_TOOLS = ["ask_user_question", "exit_plan_mode", "enter_plan_mode"]
```

**Verify:**
```bash
python -c "from vibe.core.tools.builtins.enter_plan_mode import EnterPlanMode; assert EnterPlanMode.mutates_state is False"
```

---

## STEP 7 — `vibe/core/tools/builtins/exit_plan_mode.py` (run-body delta)

> HARD DEPS already satisfied by STEP 1 (`request_fork_to_dev_callback`) + STEP 3 (`pre_plan_profile`).

**7a. Imports** — anchor: header block lines 3-23. Replace with the augmented header adding `import re`, `import time`, `from pathlib import Path`, `from vibe.core.logger import logger`, `from vibe.core.paths import PLANS_DIR`, `from vibe.core.utils.io import read_safe`, plus the module-level `_PLAN_FILE_PATTERN`, `_FALLBACK_RECENT_WINDOW_S`, and `_find_recent_plan_file()` helper. Use the exact NEW block from the spec's `exit_plan_mode-delta` first `change`.

**7b. description + mutates_state** — anchor: `description` ClassVar (lines 43-48) followed by `@classmethod def format_call_display`. Apply the reworded description (context-wipe semantics) and add `mutates_state: ClassVar[bool] = False` right after it. (This is STEP 2's exit_plan_mode entry, done here.)

**7c. run() body** — anchor: from `plan_path = str(ctx.plan_file_path) if ctx.plan_file_path else ""` (line 74) through the final `else` block (line 137). **Keep the three pre-guards (lines 65-72) untouched.** Replace lines 74-137 with the spec's NEW body:
- Resolve plan_path via `ctx.plan_file_path` → fallback `_find_recent_plan_file()` → raise `"No plan file found"`.
- `read_safe(plan_path).text`; raise on `OSError`; raise `"Plan file is empty"` on whitespace-only.
- 3-choice AskUserQuestion with **`footer_note=f"Plan: {plan_path} (Ctrl+G to edit)"`** (KEEP v2.13's footer_note; do NOT add `content_preview`).
- Auto-approve → `target_profile = ACCEPT_EDITS`.
- Request-approval → `stashed = ctx.agent_manager.pre_plan_profile`; `target = stashed or DEFAULT`; defensive `available_agents` membership fallback to DEFAULT.
- `is_other` / `No` / cancelled → `switched=False`, no callback.
- Approve paths: raise `"Fork-to-dev not available"` if `ctx.request_fork_to_dev_callback is None`; else call it with `(plan_content, plan_path, target_profile)` and yield `switched=True`.

**Verify imports resolve:**
```bash
python -c "import vibe.core.tools.builtins.exit_plan_mode as m; print(m._FALLBACK_RECENT_WINDOW_S, bool(m._find_recent_plan_file))"
```

---

## STEP 8 — `vibe/core/middleware.py` + agent_loop import (sparse reminder)

**8a. `make_plan_agent_reminder` instructions[0]** — anchor: L154 single-string research instruction.

OLD: `"Research the user's query using read-only tools (grep, read_file, etc.)"`
NEW:
```python
        "Research the user's query using read-only tools (grep, read_file, etc.). "
        "For deep / parallel code search, dispatch read-only `task` subagents "
        '(e.g. `agent: "explore"`) — multiple in parallel if you need to '
        "investigate several areas at once."
```

**8b. `make_plan_agent_sparse_reminder`** — insert between `make_plan_agent_reminder`'s closing `"""` (≈L179) and `PLAN_AGENT_EXIT = ...` (L182):
```python
def make_plan_agent_sparse_reminder(plan_file_path: str) -> str:
    """Short reminder injected periodically while plan mode stays active, so
    the LLM doesn't drift back into making edits across long planning turns.
    """
    return (
        f"<{VIBE_WARNING_TAG}>Plan mode still active — read-only, except the "
        f"plan file at {plan_file_path}. Call exit_plan_mode when the plan is "
        f"ready.</{VIBE_WARNING_TAG}>"
    )
```

**8c. `ReadOnlyAgentMiddleware`** — anchor: `__init__` (L194) through `reset` (L233). Replace per spec: add `sparse_reminder`/`sparse_every_n_turns` ctor params (keyword, defaulted → CHAT instantiation unaffected), `self._turns_since_reminder = 0`, `sparse_reminder_text` property, the `if is_active:` sparse-fire branch in `before_turn`, and reset both counters in `reset()`. Use the exact OLD/NEW strings from the `middleware-sparse` spec.

**8d. `agent_loop.py` import** — anchor: `from vibe.core.middleware import (...)` block (L46-62). Add `make_plan_agent_sparse_reminder,` after `make_plan_agent_reminder,`.

**8e. `_setup_middleware` PLAN instantiation** — anchor: `ReadOnlyAgentMiddleware(...)` PLAN call (L924-937). Add:
```python
                sparse_reminder=lambda: make_plan_agent_sparse_reminder(
                    self._plan_session.plan_file_path_str
                ),
                sparse_every_n_turns=5,
```

**Verify:**
```bash
python -c "
from vibe.core.middleware import ReadOnlyAgentMiddleware, make_plan_agent_sparse_reminder
m=ReadOnlyAgentMiddleware(lambda: type('P',(),{'name':'plan'})(), 'plan', 'R', 'X', sparse_reminder='S', sparse_every_n_turns=3)
import asyncio
async def go():
    r=[await m.before_turn(None) for _ in range(5)]
    msgs=[x.message for x in r]
    assert msgs[0]=='R' and msgs[3]=='S', msgs
asyncio.run(go()); print('sparse ok')"
```

---

## STEP 9 — `vibe/core/agent_loop.py` (gate + fork-to-dev + detect + event suppression)

> HARD DEPS: STEP 1 (`request_fork_to_dev_callback`, `mutates_state`), STEP 3 (`pre_plan_profile`), STEP 4 (PLAN profile), STEP 8 (sparse import).

**9a. AgentSafety import** — L25: `from vibe.core.agents.models import AgentProfile, BuiltinAgentName` → add `AgentSafety`.

**9b. New imports** — after the permissions import block (≈L93-98): confirm `PermissionContext`/`ToolPermission` already imported (they are). ADD:
```python
from vibe.core.tools.builtins.ask_user_question import (
    AskUserQuestionArgs,
    AskUserQuestionResult,
    Choice,
    Question,
)
from vibe.core.utils.io import read_safe
```
And ensure `from typing import cast` is present (add if absent).

**9c. `_PLAN_GATE_BYPASS_TOOLS`** — module level after `ToolDecision` class / before `class AgentLoopError` (L160-166). **TRIMMED to bash only:**
```python
# Tools in PLAN whose ALWAYS resolve_permission verdict bypasses the hard
# write gate. write_file/search_replace are NOT here: v2.13's PLAN profile
# _plan_overrides narrows them to the plan-file path via the permission layer.
# The hard mutates_state gate is scoped to bash (bypass-if-ALWAYS) + task
# (SAFE carve-out) + everything-else-blocked (MCP, non-SAFE task).
_PLAN_GATE_BYPASS_TOOLS = frozenset({"bash"})
```

**9d. `__init__` state** — after `self.entrypoint_metadata = entrypoint_metadata` (≈L490). Leave v2.13's `_pending_injected_messages`/ExperimentManager untouched. Insert:
```python
        # Pending fork-to-dev request set by ExitPlanMode / software-driven
        # plan confirmation. Tuple of (plan_text, plan_path, target_profile).
        # Consumed by the host app after the current act() returns.
        self._pending_fork_to_dev: tuple[str, Path, str] | None = None
        # Set when a tool writes/edits the current plan file in PLAN profile;
        # reset at the start of each outer turn (see _conversation_loop).
        self._plan_modified_in_turn: bool = False
```

**9e. `_conversation_loop` turn reset** — anchor: the `try:` at L1065 before `should_break_loop = False`. Insert as first statement inside `try:`:
```python
            # Reset once per act(), accumulated across inner tool-chain
            # iterations so the popup fires at end-of-turn even when the plan
            # write happened in an earlier iteration.
            self._plan_modified_in_turn = False
```

**9f. `_conversation_loop` break logic** — anchor: the block at L1091-1100. **KEEP** the `if self._drain_pending_injections(): should_break_loop = False` line where v2.13 has it (L1094, above `if user_cancelled`). Replace from `if user_cancelled: return` through the hook guard:
```python
                if user_cancelled:
                    return

                # Fork-to-dev short-circuit: a tool (exit_plan_mode) or the
                # software-driven confirmation staged a fork. Break out so the
                # host app can wipe context and re-enter act() in dev profile.
                if self._pending_fork_to_dev is not None:
                    should_break_loop = True
                elif should_break_loop:
                    # LLM tool chain settled. Software-driven plan confirmation:
                    # if the plan file was modified this turn, deterministically
                    # prompt the user to fork-to-dev (smaller models often skip
                    # exit_plan_mode). May stage _pending_fork_to_dev.
                    await self._maybe_prompt_plan_confirmation()

                if (
                    should_break_loop
                    and self._pending_fork_to_dev is None
                    and self._hooks_manager
                ):
```
(Hook body unchanged. Hooks skipped when discarding a forked turn.)

**9g. `_handle_session_plan_events` neutering** — anchor: L1141-1150. **Replace the whole method body with a no-op:**
```python
    def _handle_session_plan_events(self, event: BaseEvent) -> BaseEvent | None:
        # HYBRID: the fork's exit_plan_mode tool + software-driven
        # _maybe_prompt_plan_confirmation own the plan-exit UX (fork-to-dev),
        # so we do NOT fire the native review-in-place PlanReviewRequestedEvent
        # / PlanReviewEndedEvent here — doing so would mount a PlanFileMessage
        # that fork_to_dev() immediately wipes. PlanSession is still used for
        # plan-file path generation only. INVARIANT: exit_plan_mode is
        # fork-or-stay (never review-in-place); if that changes, revisit this.
        return None
```
Leave imports `PlanReviewRequestedEvent`/`PlanReviewEndedEvent` (L116-117) and the call site (L1173) in place. `_handle_plan_review_ended` becomes dead code — leave it to minimize churn.

**9h. Hard plan write-gate** — anchor: `_execute_tool_call`, after `tool_instance = self.tool_manager.get(...)` and BEFORE `decision: ToolDecision | None = None` (≈L1275). Insert the gate scoped to `mutates_state` + bash-bypass-if-ALWAYS + task→SAFE carve-out (verbatim from `agent_loop-plan-dispatch` spec). The contract substring `[Plan mode: write operations disabled]` must be exact. write_file/search_replace are intentionally NOT gated here.

**9i. InvokeContext construction** — anchor: kwargs block (L1311-1324). Add `request_fork_to_dev_callback=self.request_fork_to_dev,` after `switch_agent_callback=self.switch_agent,`. KEEP `permission_store=self._permission_store,`.

**9j. Plan-modified detection** — anchor: inside `_handle_tool_response` (method at L1445), immediately after the `self.messages.append(...)` tool-response append and before the `if span is not None:` telemetry block. Insert the spec's `status == "success" and active_profile == PLAN and tool_name in ("write_file","search_replace")` block; compare `Path(args_path).resolve() == self._plan_session.plan_file_path.resolve()`; set `self._plan_modified_in_turn = True`. Use `self.agent_profile.name` (property exists). **First verify the `status` Literal values** (`"success"/"failure"/"skipped"`).

**9k. `_maybe_prompt_plan_confirmation`** — insert just before `_handle_tool_response`. Use the spec's full method, with the **defensive guard**: `stashed = getattr(self.agent_manager, "pre_plan_profile", None)` (degrades to DEFAULT instead of AttributeError; STEP 3 makes it present anyway). This method uses `content_preview=plan_content` on its AskUserQuestionArgs — that is acceptable here only if v2.13's `AskUserQuestionArgs` has `content_preview`; **verify** it before applying. If v2.13 `AskUserQuestionArgs` lacks `content_preview`, drop that kwarg and add `footer_note=f"Plan: {plan_path} (Ctrl+G to edit)"` instead, to stay consistent with STEP 7c.

> ⚠️ CONSISTENCY CHECK: STEP 7c omits `content_preview` (v2.13 has no such field per the exit-delta spec). STEP 9k's fork source uses it. **Resolve by grepping `AskUserQuestionArgs` fields once** — if absent, both STEP 7 and STEP 9 must use `footer_note`. Do this check before applying 9k.

**9l. fork-to-dev API methods** — insert before `@requires_init async def clear_history` (L1856). Add `pending_fork_to_dev` property, `request_fork_to_dev(...)`, and `@requires_init async def fork_to_dev()` (clear `_pending` up-front → `await clear_history()` → `await switch_agent(target)` → return seed string). Verbatim from spec.

**9m. `clear_history` plan-state wipe** — anchor: between `self.tool_manager.reset_all()` (L1878) and `await self._reset_session(keep_parent=False)` (L1879). **KEEP the `await`** (v2.13 `_reset_session` is async). Insert:
```python
        # Wipe session-scoped plan state so /clear and fork-to-dev start clean.
        self._plan_session = PlanSession()
        self._pending_fork_to_dev = None
        self._plan_modified_in_turn = False
        if hasattr(self.agent_manager, "_pre_plan_profile"):
            self.agent_manager._pre_plan_profile = None
```
(`hasattr` guard is belt-and-suspenders; STEP 3 guarantees the attr.)

**9n. `switch_agent` plan_session rotation** — anchor: `switch_agent` body (L1956-1960). Replace per spec to capture `leaving_plan` before switch and rotate `self._plan_session = PlanSession()` after `reload_with_initial_messages` when leaving PLAN.

**Verify STEP 9 imports/compile:**
```bash
python -c "import vibe.core.agent_loop as al; assert al._PLAN_GATE_BYPASS_TOOLS == frozenset({'bash'}); assert hasattr(al.AgentLoop, 'fork_to_dev'); assert hasattr(al.AgentLoop, 'pending_fork_to_dev')"
```

---

## STEP 10 — UI / drivers (`commands.py`, `app.py`, `plan_mode_indicator.py`, `app.tcss`, `acp_agent_loop.py`)

> HARD DEPS: STEP 3 (`pre_plan_profile`), STEP 9 (`pending_fork_to_dev`, `fork_to_dev`). Land LAST.

**10a. CREATE `vibe/cli/textual_ui/widgets/plan_mode_indicator.py`** — verbatim from spec (subclass `NoMarkupStatic`, pass `id="plan-mode-indicator"`, `set_active(bool)` toggles `[PLAN]` + `display`).

**10b. `vibe/cli/commands.py`** — anchor: `"compact": Command(...)` then `"exit": Command(`. Insert the `"plan"` command (aliases `{"/plan"}`, handler `_toggle_plan_mode`) between them. Do NOT add `agents`/`stat` (native already).

**10c. `vibe/cli/textual_ui/app.py`** — six edits:
1. Import after `from vibe.core.agents import AgentProfile` (L141): add `from vibe.core.agents.models import BuiltinAgentName`.
2. Widget import after `PathDisplay` import (≈L97): add `from vibe.cli.textual_ui.widgets.plan_mode_indicator import PlanModeIndicator`.
3. `__init__` after `self._banner: Banner | None = None` (≈L437): add `self._plan_indicator: PlanModeIndicator | None = None`.
4. `compose()` bottom-bar (L527-530): mount `yield PlanModeIndicator()` between `PathDisplay` and the spacer.
5. `on_mount()` after `self._feedback_bar = self.query_one(FeedbackBar)`: cache indicator + `set_active(active_profile.name == BuiltinAgentName.PLAN)`.
6. `_on_profile_changed` (L3112-3114): append the `if self._plan_indicator is not None: set_active(...)` block (drives chip on Shift+Tab cycling for free).

**10d. `_handle_agent_loop_turn` while-loop wrap** — anchor: the single `act()` call block (L1571-1578). Replace with the `while True:` drain loop: rotate `message_id` via `str(uuid4())` and `auto_title→None` on fork re-entry; break when `pending_fork_to_dev is None`; else `current_prompt = await self._handle_pending_fork()`. (Confirm `uuid4` imported.)

**10e. CREATE `_handle_pending_fork`** — insert before `_resolve_turn_error_message` (L1610). Verbatim from spec: remove loading widget, finalize streaming, `seed = await self.agent_loop.fork_to_dev()`, reset UI, clear messages area, mount `UserCommandMessage("Plan approved — wiped planning context...")` + `UserMessage(seed, message_index=1)`, call `_on_profile_changed()`, return seed.

**10f. CREATE `_toggle_plan_mode`** — insert after `_compact_history`. **CRITICAL:** use `asyncio.run_coroutine_threadsafe(coro, loop).result()` (NOT the fork's `asyncio.run()` — that deadlocks). Reuse native `_switch_agent_generation` guard + `group="switch_agent", exclusive=True` worker. Includes arg-rejection, agent-running, and `_current_bottom_app != BottomApp.Input` guards; reads `manager.pre_plan_profile` for the un-toggle target.

**10g. `vibe/cli/textual_ui/app.tcss`** — anchor: the `PathDisplay,\nContextProgress {` rule. Insert a `#plan-mode-indicator` rule above it (`color: $text-warning; text-style: bold;`; fall back to `$text-muted` if the token is undefined).

**10h. `vibe/acp/acp_agent_loop.py` `_run_agent_loop` wrap** — anchor: L1240-1327. Wrap the `aclosing(act())`/`async for` body in `while True:`, rename arg `rendered_prompt→current_prompt`, indent the existing async-for body +4, append the fork-drain tail (`if pending_fork_to_dev is None: break; current_prompt = await fork_to_dev(); client_message_id=None; turn_auto_title=None`). Indentation is the error-prone part — apply carefully and run the ACP suite.

---

## Consolidated native-plan reconciliation (the crux: PlanReviewRequested-before-wipe)

The single hardest seam is v2.13's **review-in-place** machinery vs the fork's **fork-to-dev**. v2.13 fires `PlanReviewRequestedEvent` from `_handle_session_plan_events` on the `exit_plan_mode` **ToolCallEvent** (L1144), which the Textual `EventHandler` turns into a mounted `PlanFileMessage` for in-place review. The fork replaces that flow entirely.

**Exact chosen approach (no half-measures):**

1. **Suppress unconditionally, not flag-gate.** `_handle_session_plan_events` is rewritten to `return None` always (STEP 9g). Flag-gating on `_pending_fork_to_dev` is impossible because that flag is unset at *ToolCallEvent* time — `exit_plan_mode.run()` (which sets it) executes *after* the ToolCallEvent is emitted. Since in this hybrid `exit_plan_mode` is **always** fork-or-stay (never review-in-place), the full no-op is the only correct fix. The invariant is documented in the method comment.

2. **PlanSession survives, downgraded to path-generation only.** `_plan_session.plan_file_path` / `plan_file_path_str` still drive the plan-file path, the middleware reminders, and the plan-modified detection. `read/snapshot_content_hash/has_content_changed` are simply unused now.

3. **No UI deletion.** `PlanReviewRequestedEvent`/`PlanReviewEndedEvent` imports, the call site (L1173, now always falsy), the EventHandler cases, and `PlanFileMessage` all remain — they are just never emitted from `agent_loop`. `_handle_plan_review_ended` becomes dead code; left in place to minimize diff.

4. **Wipe happens after the loop drains, never mid-review.** `request_fork_to_dev` only *stages* a tuple; `_conversation_loop` short-circuits `should_break_loop=True`; the host driver calls `fork_to_dev()` *after* `act()` returns. Order inside `fork_to_dev`: clear `_pending` → `await clear_history()` (which itself resets `_plan_session`, pending, modified flag, `_pre_plan_profile`) → `await switch_agent(target)` (rotates plan_session) → return seed. Because no `PlanReviewRequestedEvent` is ever emitted, there is no in-flight review to race; the "do not wipe during PlanReview" concern is structurally eliminated rather than guarded.

5. **Transient PlanFileMessage double-wipe is impossible**, not merely cosmetic — since `_handle_session_plan_events` returns None, no `PlanFileMessage` is ever mounted on the exit path, so `_handle_pending_fork`'s `remove_children()` has nothing to clobber. (If a future change re-enables review-in-place, `_handle_pending_fork`'s `remove_children()` is the authoritative wipe as the documented fallback.)

6. **write_file/search_replace stay native-enforced.** `_plan_overrides` keeps them at `permission="never"` + plans allowlist; the agent_loop hard gate explicitly does NOT list them (`_PLAN_GATE_BYPASS_TOOLS = {"bash"}` only). Two non-overlapping mechanisms: permission layer for file tools, `mutates_state` hard gate for bash/task/MCP.

---

## Test plan

**Migrate from fork (port + adapt to v2.13 paths):**

| Fork test | New location | Verify |
|---|---|---|
| `test_enter_plan_mode` | `tests/tools/test_enter_plan_mode.py` (CREATE) | mutates_state False; errors w/o agent_manager (`"agent manager"`); errors when already PLAN (`"plan mode"`); errors w/o user_input_callback (`"interactive UI"`); yes→switch via `switch_agent_callback(PLAN)` and `switch_profile` NOT called; yes fallback→`switch_profile(PLAN)`; no→no switch; cancel→no switch. Import `collect_result` from `tests.mock.utils`. |
| `test_exit_plan_mode` | existing `tests/tools/test_exit_plan_mode.py` (rewrite assertions) | `"No plan file found"` when path None + empty PLANS_DIR; `_find_recent_plan_file` fallback fires + `logger.warning`; `"Plan file is empty"` on whitespace; auto-approve→callback `(content, path, ACCEPT_EDITS)`; request-approval→stashed pre_plan_profile; pre_plan None→DEFAULT; stashed-not-in-available→DEFAULT; is_other / No / cancelled→no callback; callback None on approve→`"Fork-to-dev not available"`. Pre-guards (≠PLAN, no user_input_callback) unchanged. `_find_recent_plan_file` ignores non-matching names + >24h files. |
| `test_agent_plan_mode_dispatch` | `tests/.../test_agent_plan_mode_dispatch.py` | gate blocks MCP/non-SAFE-task with exact substring `[Plan mode: write operations disabled]`; bash read-only (ALWAYS)→executes, bash mutating→blocked; task→SAFE (explore) allowed, task→non-SAFE blocked; **TRIM check**: write_file/search_replace to plan path SUCCEED (native), non-plan write blocked by permission layer not the gate; `_maybe_prompt_plan_confirmation` fires on plan-file write, stages ACCEPT_EDITS on "Yes, and auto approve edits", leaves pending None on "No, keep refining"; `fork_to_dev` order (clear before switch) + pending cleared up-front; `clear_history` wipes plan state + `_reset_session` awaited (no un-awaited-coroutine warning); `switch_agent` rotates plan_file_path; hooks skipped when `_pending_fork_to_dev` set. |
| `test_plan_command` | `tests/.../test_plan_command.py` | `/plan` toggles to PLAN + indicator visible; second `/plan` restores pre_plan profile + indicator hidden; `/plan on` rejected; `/plan` blocked while agent running; no-deadlock smoke (`run_coroutine_threadsafe` path completes); fork-to-dev drain (app): two act() calls, messages cleared, `UserCommandMessage` + `UserMessage(seed, index=1)` mounted, `_on_profile_changed` fired. |
| middleware sparse | `tests/.../test_middleware*.py` (extend) | entry→full reminder; turns 2..N-1→CONTINUE; turn N→SPARSE; reset on exit + on `reset()`; `sparse_reminder_text` None→never fires; lazy callable; CHAT instantiation (no sparse kwarg) unchanged. **Companion risk**: confirm prepend-ack behavior for `[tool, user]` — if v2.13 lacks it, a sparse reminder after a tool turn may yield `[tool, user, user]` rejected by strict backends. |
| `test_mutates_state` | new or fold into base tests | `BaseTool.mutates_state is True`; True set {bash, task, search_replace, write_file}; False set {ask_user_question, exit_plan_mode, enter_plan_mode, grep, read_file, skill, todo, webfetch, websearch}; `InvokeContext` has `request_fork_to_dev_callback` field default None. |

**Rely on upstream `test_plan_session`** unchanged (PlanSession path-generation is untouched — only its consumer role narrowed).

**Regression gate:** `pytest -q` full suite. **Expect breakage** in any existing test asserting `PlanReviewRequestedEvent`/`PlanReviewEndedEvent` fires on `exit_plan_mode` — these encode the replaced review-in-place contract and must be **updated/removed**, not "fixed". Enumerate them first: `grep -rn "PlanReviewRequestedEvent\|PlanReviewEndedEvent\|_handle_start_plan_review\|PlanFileMessage" tests/`.

**Per-step smoke commands** are inlined in STEPS 1-9 above (run after each step).

---

## Top risks (ranked)

1. **Neutering `_handle_session_plan_events` breaks native review tests (HIGH).** Any v2.13 test asserting `PlanReviewRequestedEvent` firing now fails by design. Enumerate and update/remove before merge — do not patch around them. This is the load-bearing behavioral change.

2. **Cross-step runtime coupling (HIGH).** `request_fork_to_dev_callback` (base.py), `pre_plan_profile` (manager), `pending_fork_to_dev`/`fork_to_dev` (agent_loop) are referenced across STEP 7/9/10. Applying out of the prescribed order yields AttributeError at runtime (not import time). The `getattr`/`hasattr` guards in 9k/9m make agent_loop import-safe in isolation, but full flow requires 1→3→4→8→9→10 in order.

3. **`content_preview` field inconsistency (MEDIUM, must resolve before 9k).** STEP 7c omits `content_preview` (exit-delta spec says v2.13 lacks the field); STEP 9k's fork source uses it. Grep `AskUserQuestionArgs` fields once; if absent, strip `content_preview` from 9k and use `footer_note`. Failing to check → constructor TypeError at first plan-confirmation popup.

4. **`asyncio.run()` deadlock in `_toggle_plan_mode` (MEDIUM).** The fork's pattern reuses a new event loop and deadlocks against Textual's running loop. STEP 10f mandates `run_coroutine_threadsafe(coro, loop).result()` + native `_switch_agent_generation` guard + `group="switch_agent"`. A regression test must guard against re-introducing `asyncio.run()`.

5. **`_reset_session` await drop (MEDIUM).** v2.13's `_reset_session` is async; the fork's is sync. STEP 9m must keep `await self._reset_session(keep_parent=False)`. Dropping it leaves a never-awaited coroutine and a silently un-reset session.

6. **ACP `_run_agent_loop` re-indentation (MEDIUM).** STEP 10h re-indents ~77 lines +4 under `while True:`, renames `rendered_prompt→current_prompt`, rotates `auto_title→None`. Easy to mis-indent by hand; run the ACP suite immediately after.

7. **`_handle_tool_response` status Literal + `mutates_state`/`resolve_permission` API drift (LOW-MEDIUM).** Plan-modified detection keys on `status == "success"` — verify the Literal. The bash bypass try/except degrades safely (treats failure as not-allowlisted → blocked = conservative), so drift over-blocks rather than under-blocks.

8. **Missing prepend-ack companion for sparse reminders (LOW-MEDIUM).** Without the fork's `[tool, user]` ack insertion, a sparse reminder right after a tool-result turn can produce `[tool, user, user]` rejected by strict Mistral/vLLM backends (400). Port the prepend-ack change alongside if those backends are in use.

9. **bash allowlist redirect gap (LOW, pre-existing).** `ls > file` / `cmd | tee out` evade token-based allowlisting — a redirect could slip a write through the PLAN bash gate. Carried verbatim from the fork; not introduced here.

10. **GENERAL_PURPOSE subagent is read/write capable (LOW, by design).** It inherits the full tool set (no `enabled_tools` restriction), unlike read-only EXPLORE. Intentional (mirrors Claude Code) but reviewers should know it is dispatchable with write tools only when explicitly allowlisted (Task allowlist stays `[EXPLORE]`).
````

Files referenced (all absolute):
- `/home/zdy/mistral-vibe-2.13/vibe/core/tools/base.py`
- `/home/zdy/mistral-vibe-2.13/vibe/core/tools/builtins/{bash,task,search_replace,write_file,ask_user_question,exit_plan_mode,grep,read_file,skill,todo,webfetch,websearch}.py`
- `/home/zdy/mistral-vibe-2.13/vibe/core/tools/builtins/enter_plan_mode.py` (CREATE)
- `/home/zdy/mistral-vibe-2.13/vibe/core/agents/{manager,models}.py`
- `/home/zdy/mistral-vibe-2.13/vibe/core/prompts/__init__.py` + `general_purpose.md` (CREATE)
- `/home/zdy/mistral-vibe-2.13/vibe/core/{middleware,agent_loop}.py`
- `/home/zdy/mistral-vibe-2.13/vibe/cli/commands.py`, `vibe/cli/textual_ui/app.py`, `vibe/cli/textual_ui/app.tcss`, `vibe/cli/textual_ui/widgets/plan_mode_indicator.py` (CREATE)
- `/home/zdy/mistral-vibe-2.13/vibe/acp/acp_agent_loop.py`
- `/home/zdy/mistral-vibe-2.13/tests/tools/test_enter_plan_mode.py` (CREATE), `test_exit_plan_mode.py`

Note: target tree is on branch `feat/port-2.13` (not `integration/upstream-v2.9.6`); all spec anchors verified against the working tree. Two spec corrections folded in: use `dataclasses.fields` (not `inspect.fields`) in the STEP 1 verify, and resolve the `content_preview` field question before applying STEP 9k.
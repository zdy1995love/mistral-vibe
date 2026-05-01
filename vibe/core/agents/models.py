from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum, auto
from pathlib import Path
import tomllib
from typing import TYPE_CHECKING, Any

from vibe.core.paths import PLANS_DIR

if TYPE_CHECKING:
    from vibe.core.config import VibeConfig


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class AgentSafety(StrEnum):
    SAFE = auto()
    NEUTRAL = auto()
    DESTRUCTIVE = auto()
    YOLO = auto()


class AgentType(StrEnum):
    AGENT = auto()
    SUBAGENT = auto()


class BuiltinAgentName(StrEnum):
    DEFAULT = "default"
    CHAT = "chat"
    PLAN = "plan"
    ACCEPT_EDITS = "accept-edits"
    AUTO_APPROVE = "auto-approve"
    EXPLORE = "explore"
    LEAN = "lean"


@dataclass(frozen=True)
class AgentProfile:
    name: str
    display_name: str
    description: str
    safety: AgentSafety
    agent_type: AgentType = AgentType.AGENT
    overrides: dict[str, Any] = field(default_factory=dict)
    install_required: bool = False

    def apply_to_config(self, base: VibeConfig) -> VibeConfig:
        from vibe.core.config import VibeConfig as VC

        merged = _deep_merge(
            base.model_dump(),
            {k: v for k, v in self.overrides.items() if k != "base_disabled"},
        )
        base_disabled = self.overrides.get("base_disabled")
        if isinstance(base_disabled, list):
            merged["disabled_tools"] = list({
                *base_disabled,
                *merged.get("disabled_tools", []),
            })

        return VC.model_validate(merged)

    @classmethod
    def from_toml(cls, path: Path) -> AgentProfile:
        with path.open("rb") as f:
            data = tomllib.load(f)
        return cls(
            name=path.stem,
            display_name=data.pop("display_name", path.stem.replace("-", " ").title()),
            description=data.pop("description", ""),
            safety=AgentSafety(data.pop("safety", AgentSafety.NEUTRAL)),
            agent_type=AgentType(data.pop("agent_type", AgentType.AGENT)),
            overrides=data,
        )


CHAT_AGENT_TOOLS = ["grep", "read_file", "ask_user_question", "task"]


# Read-only bash commands the LLM is allowed to run while in PLAN mode.
# The plan-mode dispatch gate honors a Bash resolve_permission ALWAYS verdict
# (allowlist hit on the first parsed sub-command) to let exploratory commands
# like `ls`, `find`, `git log` through. Anything not in this list is blocked
# with the standard "[Plan mode: write operations disabled]" error.
#
# Each entry is a command-prefix; Bash's resolve_permission matches the
# entire parsed command against `entry` or `entry + " "`. Compound commands
# (`a && b`, `a; b`, pipelines) are split first and ALL parts must match.
#
# Known gap: shell write redirections (`ls > file`, `cmd | tee out`) are NOT
# detected here — the redirect operator is outside the parsed command tokens.
# This is a pre-existing vibe-cli limitation, not specific to plan mode. If
# you need stricter safety, add a redirect detector to the dispatch gate.
_PLAN_BASH_READ_ONLY_ALLOWLIST = [
    # File listing & inspection
    "ls",
    "find",
    "tree",
    "cat",
    "head",
    "tail",
    "less",
    "more",
    "file",
    "stat",
    "wc",
    "du",
    "df",
    # Text search
    "grep",
    "egrep",
    "fgrep",
    "rg",
    "ag",
    # Path / info
    "pwd",
    "which",
    "whereis",
    "type",
    "basename",
    "dirname",
    "realpath",
    "echo",
    "date",
    "whoami",
    "uname",
    "hostname",
    "uptime",
    # Read-only process / system info
    "ps",
    "pgrep",
    "lsof",
    "id",
    "groups",
    "env",
    "printenv",
    # Git read-only operations
    "git status",
    "git log",
    "git diff",
    "git show",
    "git branch",
    "git tag",
    "git remote",
    "git rev-parse",
    "git ls-files",
    "git blame",
    "git config --get",
]


def _plan_overrides() -> dict[str, Any]:
    plans_pattern = str(PLANS_DIR.path / "*")
    return {
        # write_file / search_replace: mutating tools trip the plan-mode
        # dispatch gate. Gate respects ALWAYS verdicts from resolve_permission
        # for these tools, which the plans_pattern allowlist produces — so
        # the LLM can author the plan file as the system reminder instructs.
        # Other write paths stay blocked.
        #
        # bash: same mechanism. Allowlist of read-only commands lets the LLM
        # use `ls`, `find`, `grep`, `git log`, etc. for exploration while
        # planning. Anything outside the list (including bash with no command,
        # or compound commands containing a non-allowlisted part) is blocked.
        "tools": {
            "write_file": {"permission": "ask", "allowlist": [plans_pattern]},
            "search_replace": {"permission": "ask", "allowlist": [plans_pattern]},
            "bash": {"permission": "ask", "allowlist": _PLAN_BASH_READ_ONLY_ALLOWLIST},
        },
        # Hide the entry tool while already in plan; ExitPlanMode is the way out.
        "base_disabled": ["enter_plan_mode"],
    }


# Hide both plan-mode tools from LLM tool list in non-PLAN profiles.
# - exit_plan_mode is unusable outside PLAN (it errors).
# - enter_plan_mode was usable but was observed to degrade tool-call
#   reliability on some models (Mistral-Small-4 with vLLM, the model
#   started narrating bash commands in markdown instead of calling them).
#   Plan-mode entry stays available to users via the /plan slash command
#   and shift+tab cycle; LLM-driven entry from non-PLAN profiles is
#   removed as the cost outweighed the benefit.
_NON_PLAN_BASE_DISABLED = ["exit_plan_mode", "enter_plan_mode"]


DEFAULT = AgentProfile(
    BuiltinAgentName.DEFAULT,
    "Default",
    "Requires approval for tool executions",
    AgentSafety.NEUTRAL,
    overrides={"base_disabled": _NON_PLAN_BASE_DISABLED},
)
PLAN = AgentProfile(
    BuiltinAgentName.PLAN,
    "Plan",
    "Read-only agent for exploration and planning",
    AgentSafety.SAFE,
    overrides=_plan_overrides(),
)
CHAT = AgentProfile(
    BuiltinAgentName.CHAT,
    "Chat",
    "Read-only conversational mode for questions and discussions",
    AgentSafety.SAFE,
    overrides={"bypass_tool_permissions": True, "enabled_tools": CHAT_AGENT_TOOLS},
)
ACCEPT_EDITS = AgentProfile(
    BuiltinAgentName.ACCEPT_EDITS,
    "Accept Edits",
    "Auto-approves file edits only",
    AgentSafety.DESTRUCTIVE,
    overrides={
        "base_disabled": _NON_PLAN_BASE_DISABLED,
        "tools": {
            "write_file": {"permission": "always"},
            "search_replace": {"permission": "always"},
        },
    },
)
AUTO_APPROVE = AgentProfile(
    BuiltinAgentName.AUTO_APPROVE,
    "Auto Approve",
    "Auto-approves all tool executions",
    AgentSafety.YOLO,
    overrides={
        "bypass_tool_permissions": True,
        "base_disabled": _NON_PLAN_BASE_DISABLED,
    },
)

EXPLORE = AgentProfile(
    name=BuiltinAgentName.EXPLORE,
    display_name="Explore",
    description="Read-only subagent for codebase exploration",
    safety=AgentSafety.SAFE,
    agent_type=AgentType.SUBAGENT,
    overrides={"enabled_tools": ["grep", "read_file"], "system_prompt_id": "explore"},
)

LEAN = AgentProfile(
    name=BuiltinAgentName.LEAN,
    display_name="Lean",
    description="Specialized mode for Lean 4 code analysis, proof assistance, and theorem proving",
    safety=AgentSafety.NEUTRAL,
    agent_type=AgentType.AGENT,
    install_required=True,
    overrides={
        "system_prompt_id": "lean",
        "active_model": "leanstral",
        "providers": [
            {
                "name": "mistral-testing",
                "api_base": "https://api.mistral.ai/v1",
                "api_key_env_var": "MISTRAL_API_KEY",
                "backend": "mistral",
            }
        ],
        "models": [
            {
                "name": "labs-leanstral-2603",
                "provider": "mistral-testing",
                "alias": "leanstral",
                "thinking": "high",
                "temperature": 1.0,
                "auto_compact_threshold": 168_000,
            }
        ],
        "compaction_model": {
            "name": "mistral-small-latest",
            "provider": "mistral-testing",
            "alias": "devstral-compact",
            "temperature": 0.2,
            "thinking": "off",
        },
        "tools": {"bash": {"default_timeout": 1200}},
        # Disable both plan-mode round-trip tools: the LEAN profile is a
        # specialized model+prompt setup, and letting the LLM call
        # enter_plan_mode would silently switch to the PLAN profile and lose
        # the LEAN system prompt and model selection.
        "base_disabled": ["exit_plan_mode", "enter_plan_mode"],
    },
)

BUILTIN_AGENTS: dict[str, AgentProfile] = {
    BuiltinAgentName.DEFAULT: DEFAULT,
    BuiltinAgentName.PLAN: PLAN,
    BuiltinAgentName.ACCEPT_EDITS: ACCEPT_EDITS,
    BuiltinAgentName.AUTO_APPROVE: AUTO_APPROVE,
    BuiltinAgentName.EXPLORE: EXPLORE,
    BuiltinAgentName.LEAN: LEAN,
}

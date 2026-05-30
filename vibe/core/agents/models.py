from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum, auto
from pathlib import Path
import tomllib
from typing import TYPE_CHECKING, Any

from vibe.core.paths import PLANS_DIR
from vibe.core.utils import name_matches

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
    GENERAL_PURPOSE = "general-purpose"
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

        # Environment-level disables (set by ACP/programmatic mode) must take
        # precedence over an agent's enabled_tools allowlist
        if base.disabled_tools and merged.get("enabled_tools"):
            merged["enabled_tools"] = [
                t
                for t in merged["enabled_tools"]
                if not name_matches(t, base.disabled_tools)
            ]

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
        # write_file / search_replace stay at v2.13-native 'never' + plans
        # allowlist: a plans-dir path match resolves to ALWAYS (so the plan file
        # authors), everything else hard-denied. bash: read-only command
        # allowlist lets exploratory ls/find/grep/git-log through the dispatch
        # gate (resolve_permission -> ALWAYS on full match); anything else blocked.
        "tools": {
            "write_file": {"permission": "never", "allowlist": [plans_pattern]},
            "search_replace": {"permission": "never", "allowlist": [plans_pattern]},
            "bash": {"permission": "ask", "allowlist": _PLAN_BASH_READ_ONLY_ALLOWLIST},
        },
        # Hide the entry tool while already in plan; ExitPlanMode is the way out.
        "base_disabled": ["enter_plan_mode"],
    }


# Hide both plan-mode tools from the LLM tool list in non-PLAN profiles.
# exit_plan_mode is unusable outside PLAN; enter_plan_mode was observed to
# degrade tool-call reliability on some local models — plan entry stays
# available to users via the /plan slash command and shift+tab cycle.
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
    overrides={"bypass_tool_permissions": True, "base_disabled": _NON_PLAN_BASE_DISABLED},
)

EXPLORE = AgentProfile(
    name=BuiltinAgentName.EXPLORE,
    display_name="Explore",
    description="Read-only subagent for codebase exploration",
    safety=AgentSafety.SAFE,
    agent_type=AgentType.SUBAGENT,
    overrides={"enabled_tools": ["grep", "read_file"], "system_prompt_id": "explore"},
)

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
        "base_disabled": ["exit_plan_mode", "enter_plan_mode"],
    },
)

BUILTIN_AGENTS: dict[str, AgentProfile] = {
    BuiltinAgentName.DEFAULT: DEFAULT,
    BuiltinAgentName.PLAN: PLAN,
    BuiltinAgentName.ACCEPT_EDITS: ACCEPT_EDITS,
    BuiltinAgentName.AUTO_APPROVE: AUTO_APPROVE,
    BuiltinAgentName.EXPLORE: EXPLORE,
    BuiltinAgentName.GENERAL_PURPOSE: GENERAL_PURPOSE,
    BuiltinAgentName.LEAN: LEAN,
}

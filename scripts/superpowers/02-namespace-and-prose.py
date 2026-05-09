"""Round 2: fix P0 (namespace) + P1 (misleading prose)."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path("/home/zdy/.vibe/vendor/superpowers/skills")

# Strip plugin-namespace prefix — vibe uses bare skill names
# Match `superpowers:<name>` where <name> is one of our 14 skills.
SKILL_NAMES = [
    "brainstorming", "dispatching-parallel-agents", "executing-plans",
    "finishing-a-development-branch", "receiving-code-review",
    "requesting-code-review", "subagent-driven-development",
    "systematic-debugging", "test-driven-development", "using-git-worktrees",
    "using-superpowers", "verification-before-completion", "writing-plans",
    "writing-skills",
]
NAMESPACE_RX = re.compile(r"\bsuperpowers:(" + "|".join(SKILL_NAMES) + r")\b")


def fix_namespace(text: str) -> tuple[str, int]:
    return NAMESPACE_RX.subn(r"superpowers-\1", text)


# ----- targeted prose fixes -----

# executing-plans: vibe has subagents, the "if your platform has subagents" caveat is misleading
EXEC_PLANS_OLD = """**Note:** Tell your human partner that Superpowers works much better with access to subagents. The quality of its work will be significantly higher if run on a platform with subagent support (such as Claude Code or Codex). If subagents are available, use subagent-driven-development instead of this skill."""
EXEC_PLANS_NEW = """**Note:** mistral-vibe supports subagents via the `task` tool — prefer subagent-driven-development over this skill for higher-quality results. Use this skill only when running tasks in the same context (no subagent dispatch)."""

# using-git-worktrees: vibe has no native worktree tool, so the EnterWorktree mention is wrong
WORKTREE_OLD_53 = """The user has asked for an isolated workspace (Step 0 consent). Do you already have a way to create a worktree? It might be a tool with a name like `EnterWorktree`, `WorktreeCreate`, a `/worktree` command, or a `--worktree` flag. If you do, use it and skip to Step 3."""
WORKTREE_NEW_53 = """The user has asked for an isolated workspace (Step 0 consent). mistral-vibe has no native worktree tool — proceed to Step 1 and use `git worktree add` directly via the `bash` tool."""

WORKTREE_OLD_203 = """- Use `git worktree add` when you have a native worktree tool (e.g., `EnterWorktree`). This is the #1 mistake — if you have it, use it."""
WORKTREE_NEW_203 = """- Use `git worktree add` directly via the `bash` tool — mistral-vibe has no native worktree tool, so this is the canonical path."""

# writing-skills: add vibe path to the personal-skills directory list
WRITING_SKILLS_OLD = """**Personal skills live in agent-specific directories (`~/.claude/skills` for Claude Code, `~/.agents/skills/` for Codex)**"""
WRITING_SKILLS_NEW = """**Personal skills live in agent-specific directories (`~/.vibe/skills/` for mistral-vibe, `~/.claude/skills` for Claude Code, `~/.agents/skills/` for Codex)**"""

# using-superpowers: simplify "How to Access Skills" to be vibe-first
USING_SP_OLD = """## How to Access Skills

**In Claude Code:** Use the `skill` tool. When you invoke a skill, its content is loaded and presented to you—follow it directly. Never use the `read_file` tool on skill files.

**In Copilot CLI:** Use the `skill` tool. Skills are auto-discovered from installed plugins. The `skill` tool works the same as Claude Code's `skill` tool.

**In Gemini CLI:** Skills activate via the `activate_skill` tool. Gemini loads skill metadata at session start and activates the full content on demand.

**In other environments:** Check your platform's documentation for how skills are loaded.

## Platform Adaptation

Skills use Claude Code tool names. Non-CC platforms: see `references/copilot-tools.md` (Copilot CLI), `references/codex-tools.md` (Codex) for tool equivalents. Gemini CLI users get the tool mapping loaded automatically via GEMINI.md."""

USING_SP_NEW = """## How to Access Skills

Use the `skill` tool with the bare skill name (e.g. `name="brainstorming"`, no plugin prefix). The skill body is injected into context — follow it directly. Never use `read_file` on SKILL.md files.

Skills are also user-invocable as `/<skill-name>` slash commands.

## Platform Adaptation

Tool names in skill bodies were translated from Claude Code naming during the vibe port. If a skill references a Claude-Code-style tool that's not yet translated, use the mapping in `references/` (legacy mapping files for Copilot/Codex/Gemini)."""


PROSE_RULES: list[tuple[Path, str, str]] = [
    (ROOT / "executing-plans" / "SKILL.md", EXEC_PLANS_OLD, EXEC_PLANS_NEW),
    (ROOT / "using-git-worktrees" / "SKILL.md", WORKTREE_OLD_53, WORKTREE_NEW_53),
    (ROOT / "using-git-worktrees" / "SKILL.md", WORKTREE_OLD_203, WORKTREE_NEW_203),
    (ROOT / "writing-skills" / "SKILL.md", WRITING_SKILLS_OLD, WRITING_SKILLS_NEW),
    (ROOT / "using-superpowers" / "SKILL.md", USING_SP_OLD, USING_SP_NEW),
]


def main() -> int:
    # Pass A: namespace stripping across all .md
    ns_changed = 0
    for f in sorted(ROOT.rglob("*.md")):
        text = f.read_text()
        new, n = fix_namespace(text)
        if n:
            f.write_text(new)
            ns_changed += 1
            print(f"  namespace strip ({n}x): {f.relative_to(ROOT)}")
    print(f"namespace pass: {ns_changed} files changed")

    # Pass B: targeted prose replacements
    print("\nprose pass:")
    for f, old, new in PROSE_RULES:
        text = f.read_text()
        if old not in text:
            print(f"  ! NOT FOUND in {f.relative_to(ROOT)}: {old[:60]}...")
            continue
        f.write_text(text.replace(old, new))
        print(f"  ✓ {f.relative_to(ROOT)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

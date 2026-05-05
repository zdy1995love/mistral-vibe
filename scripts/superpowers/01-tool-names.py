"""
One-shot translator for obra/superpowers → mistral-vibe.
Context-bound replacements only — never bare-word.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path("/home/zdy/.vibe/vendor/superpowers/skills")

# Context-bound rules: (regex, replacement, description)
# Each pattern ONLY matches when surrounded by tool-y context.
RULES: list[tuple[re.Pattern[str], str, str]] = [
    # `Skill` tool / Skill tool / "Skill tool" — case-sensitive, preserve markdown
    (re.compile(r"`Skill` tool"), "`skill` tool", "`Skill` tool → `skill` tool"),
    (re.compile(r"\bSkill tool\b"), "`skill` tool", "Skill tool → `skill` tool"),

    # Read/Write/Edit/Bash/Grep tool variants
    (re.compile(r"\bRead tool\b"), "`read_file` tool", "Read tool → `read_file` tool"),
    (re.compile(r"\bWrite tool\b"), "`write_file` tool", "Write tool → `write_file` tool"),
    (re.compile(r"\bEdit tool\b"), "`search_replace` tool (note: vibe uses SEARCH/REPLACE block format, not old/new strings)", "Edit tool → `search_replace` tool"),
    (re.compile(r"\bBash tool\b"), "`bash` tool", "Bash tool → `bash` tool"),
    (re.compile(r"\bGrep tool\b"), "`grep` tool", "Grep tool → `grep` tool"),
    (re.compile(r"\bGlob tool\b"), "`bash` tool with `find`/`ls` (vibe has no dedicated glob tool)", "Glob tool → bash+find"),
    (re.compile(r"\bAgent tool\b"), "`task` tool (model-callable subagent dispatch)", "Agent tool → `task` tool"),

    # Plan-mode tools — both bare and backticked
    (re.compile(r"`EnterPlanMode`"), "`enter_plan_mode`", "`EnterPlanMode` → `enter_plan_mode`"),
    (re.compile(r"`ExitPlanMode`"), "`exit_plan_mode`", "`ExitPlanMode` → `exit_plan_mode`"),
    (re.compile(r"\bEnterPlanMode\b"), "enter_plan_mode", "EnterPlanMode → enter_plan_mode"),
    (re.compile(r"\bExitPlanMode\b"), "exit_plan_mode", "ExitPlanMode → exit_plan_mode"),

    # Web tools
    (re.compile(r"`WebSearch`"), "`web_search`", "`WebSearch` → `web_search`"),
    (re.compile(r"`WebFetch`"), "`web_fetch`", "`WebFetch` → `web_fetch`"),
    (re.compile(r"\bWebSearch\b"), "`web_search`", "WebSearch → `web_search`"),
    (re.compile(r"\bWebFetch\b"), "`web_fetch`", "WebFetch → `web_fetch`"),

    # TodoWrite / Task* (Claude task triad)
    (re.compile(r"`TodoWrite`"), "`todo`", "`TodoWrite` → `todo`"),
    (re.compile(r"\bTodoWrite\b"), "`todo` tool", "TodoWrite → `todo` tool"),
    (re.compile(r"\bTaskCreate\b"), "`todo` tool", "TaskCreate → `todo` tool"),
    (re.compile(r"\bTaskUpdate\b"), "`todo` tool", "TaskUpdate → `todo` tool"),
    (re.compile(r"\bTaskList\b"), "`todo` tool", "TaskList → `todo` tool"),
]


def translate_file(path: Path) -> tuple[int, list[str]]:
    text = path.read_text()
    original = text
    applied: list[str] = []
    for rx, repl, desc in RULES:
        new_text, n = rx.subn(repl, text)
        if n:
            applied.append(f"{desc} ({n}x)")
        text = new_text
    if text != original:
        path.write_text(text)
        return 1, applied
    return 0, applied


def main() -> int:
    md_files = sorted(ROOT.rglob("*.md"))
    print(f"Found {len(md_files)} .md files under {ROOT}")
    changed = 0
    for f in md_files:
        n, applied = translate_file(f)
        if n:
            changed += 1
            rel = f.relative_to(ROOT)
            print(f"\n✓ {rel}")
            for a in applied:
                print(f"  - {a}")
    print(f"\nTotal files changed: {changed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

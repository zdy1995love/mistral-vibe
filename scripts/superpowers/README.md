# vibe-port translation scripts

These scripts replay the Claude Code → mistral-vibe translation that lives
on the `vibe-port` branch. Run them in order after a fresh rebase against
upstream if conflicts re-introduce Claude Code names or `superpowers:`
plugin-namespace prefixes.

## Usage

```bash
cd ~/.vibe/vendor/superpowers
git fetch upstream
git rebase upstream/main vibe-port
# If translation is partially lost during rebase:
python3 scripts/vibe-port/01-tool-names.py
python3 scripts/vibe-port/02-namespace-and-prose.py
git add -A && git commit --amend --no-edit
```

## Scripts

- **01-tool-names.py** — `Skill tool` → `` `skill` tool ``, `Read tool` → `` `read_file` tool ``, etc.
- **02-namespace-and-prose.py** — strip `superpowers:` plugin prefix (vibe uses bare names) + targeted prose fixes for executing-plans, using-git-worktrees, writing-skills, using-superpowers.

Both are idempotent — running twice is a no-op.

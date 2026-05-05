# Bundled superpowers skills

These 14 skills are vendored from [obra/superpowers](https://github.com/obra/superpowers)
and translated for mistral-vibe (tool names, plugin namespace, prose adapted).

- **Upstream:** https://github.com/obra/superpowers (MIT license — see `LICENSE.upstream`)
- **Bundled version:** `5.1.0` (matches upstream `f2cbfbe`, "Release v5.1.0")
- **Translation history:** see `scripts/superpowers/{01-tool-names.py,02-namespace-and-prose.py}`
  in the mistral-vibe repo root.

## How to refresh from upstream

To bump the bundled version:

```bash
# 1. clone fresh upstream
git clone https://github.com/obra/superpowers.git /tmp/superpowers-fresh

# 2. apply translation (in order)
python3 scripts/superpowers/01-tool-names.py        # rewrite paths in script if needed
python3 scripts/superpowers/02-namespace-and-prose.py

# 3. rsync into the bundle
rsync -a --delete /tmp/superpowers-fresh/skills/ \
                  vibe/core/skills/builtins/superpowers/skills/
cp /tmp/superpowers-fresh/LICENSE \
   vibe/core/skills/builtins/superpowers/LICENSE.upstream

# 4. update the version line in this README
# 5. run the test suite, commit
```

The translation scripts are idempotent — running them on already-translated
files is a no-op.

# What's new in this fork

- **`/agents` slash command**: List, preview, and edit agent profiles (builtin or custom TOML)
- **Builtin skills system**: Added self-awareness skill for enhanced functionality

# What's new in v2.9.5

- **`/loop` command**: Run a prompt or slash command on a recurring interval.
- **`default_agent` config**: Set which agent profile starts each session.
- **Parallel-safe history**: Multiple `vibe` instances no longer clobber each other's history file.

# What's new in v2.9.4

- **`/rename` command**: Rename the current session from the slash menu.
- **Persistent "always allow"**: Tool permissions granted with "always allow" now stick across sessions.
- **Faster bash bang commands**: `!command` runs via async subprocess.

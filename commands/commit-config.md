---
name: commit-config
description: View or change commit-commands plugin settings (e.g. toggle the enforce-commit-commands-use gate).
allowed-tools: Bash(python3:*)
---

## Context

- Current config: !`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/commit_config.py" show`

## Instructions

Show the user the current config printed above.  Then offer to toggle
`enforce-commit-commands-use` using `AskUserQuestion` with these options:

- **Enable enforcement** (set to true) — the PreToolUse hook will block raw
  `git commit` Bash calls and redirect to `/commit` or `/commitall`.
- **Disable enforcement** (set to false) — raw `git commit` is allowed;
  the gate is off.
- **Leave as-is** — make no change.

After the user chooses, run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/commit_config.py" set enforce-commit-commands-use <true|false>
```

Then print the updated config to confirm.  If the user chose "leave as-is",
just confirm the current value and exit.

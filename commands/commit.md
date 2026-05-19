---
name: commit
description: Atomic git commit of current session changes with mandatory code review and simplify pre-flight.
allowed-tools: Bash(git status:*), Bash(git diff:*), Bash(git log:*), Bash(git branch:*), Bash(git add:*), Bash(git commit:*), Bash(uv run:*)
---

## Context

- Git status: !`git status --short --branch`
- Change summary: !`git diff --stat HEAD`
- Recent commits: !`git log --oneline -10`
- Preflight determination: !`uv run --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/determine-preflight.py" 2>/dev/null || echo "DETERMINER_UNAVAILABLE — fall back to manual model-judged gating (see Steps step 1 fallback)"`

**SCOPE:** Only files changed in the **current session**. Ignore unrelated pre-existing changes — do not review, stage, or commit them.

The full diff is intentionally NOT loaded here. Fetch scoped diffs on demand with `git diff -- <path>` during review/commit — never the whole tree at once.

@${CLAUDE_PLUGIN_ROOT}/shared/commit-workflow.md

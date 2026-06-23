# commit-commands

Atomic git commits for Claude Code with a code-review + simplify pre-flight, enforcing
project git rules (conventional messages, no `git add -A`, no `--no-verify`, no AI
attribution). Replaces the `claude-plugins-official` commit-commands.

Provides `/commit` (session changes) and `/commitall` (all uncommitted changes).

## Pre-flight review

Before staging, a deterministic gate (`scripts/determine_preflight.py`) measures the changeset (Δloc, complexity, file class, path-sensitivity, git regression-gravity) and picks a review intensity:

- **trivial** (docs/data, semantic no-ops, tiny low-complexity diffs) → no review; commit directly.
- **standard** → `/code-review`.
- **sensitive / complex** → `feature-dev:code-reviewer` + `/code-review` (high on complex), **plus a parallel Codex (GPT-5) second opinion when the codex plugin is installed**.

### Codex second opinion

On the sensitive/complex tiers the pre-flight also runs a Codex review via the [OpenAI codex plugin](https://github.com/openai/codex-plugin-cc), invoking its companion script directly because the `/codex:review` slash command is `disable-model-invocation`.
It is launched as a background task so its latency overlaps the other reviewers, then collected before the issues gate.
Codex findings tagged `[P1]`/`[P2]` are auto-fixed (Critical/Important); lower findings are surfaced verbatim.

Requirements and behavior:

- **Adaptive and silent:** the determiner emits the Codex step only when the codex plugin is installed. On a host without it the step never appears — nothing is checked, nothing is printed, and the commit flow is unchanged.
- If codex is installed but not authenticated, the pre-flight pauses once to ask you to `codex login` (or skip for this commit).
- Auth runs through your OpenAI/Codex plan, not a metered Anthropic API key.
- **Cross-platform:** the install probe is pure Python (`pathlib`), so it resolves identically on macOS, Linux, and Windows (including WSL2). Point `COMMIT_CODEX_COMPANION` at a `codex-companion.mjs` for a non-standard install.
- Opt out entirely with `COMMIT_CODEX_REVIEW=0` in the environment.

## Enforcement gate

A `PreToolUse` hook (`hooks/enforce_commit_commands_hook.py`) blocks raw `git commit` Bash calls, redirecting you to `/commit` / `/commitall` so every commit goes through the pre-flight review and message hygiene.

Authorization works by **commit credit**, not by a magic string:

- Invoking `/commit` or `/commitall` mints a short-lived, **session-scoped** credit (a `!` context directive runs `scripts/commit_credit.py grant`).
- The hook allows a `git commit` only when the current session holds a valid credit — keyed by `CLAUDE_CODE_SESSION_ID`, so a credit minted in one session never authorizes a commit in another.
- A credit is a **lease**, not a single-use token: one `/commitall` run can produce several atomic commits under a single grant. Staleness is bounded by the TTL (default **300s**; widen with `commit_credit_ttl_seconds` in the config for flows whose review/HITL pauses might outlast it).

This replaces the earlier `∴ committed ∴` sentinel, which the model could trivially forge by echoing the phrase after a raw commit. There is no longer any token to append: a credit can exist only if the sanctioned command flow actually ran.

If `/commit` / `/commitall` genuinely cannot accomplish a commit (e.g. a sibling repo the command's cwd can't reach), commit it from your terminal with the `!` prefix — `! git -C <path> commit …` — which routes through your shell, bypassing the Bash-tool hook. Otherwise, when a commit is blocked, stop and surface it rather than working around the gate.

Toggle the gate with `/commit-config` (sets `enforce_commit_commands_use`).

## Install

```bash
claude plugin marketplace add joelpt/joelpt-claude-plugins
claude plugin install commit-commands@joelpt-claude-plugins
```

Then restart Claude Code. Requires read access to the private marketplace repo (`gh auth login`).

## Layout

```text
.claude-plugin/plugin.json   ← plugin manifest
commands/                    ← /commit, /commitall, /commit-config
hooks/                       ← enforce-commit-commands PreToolUse gate
scripts/                     ← pre-flight determiner, commit-credit + config CLIs
shared/                      ← shared commit logic
tst/                         ← determiner, credit, and hook tests
```

Distributed via the [`joelpt-claude-plugins`](https://github.com/joelpt/joelpt-claude-plugins)
marketplace. Bump `.claude-plugin/plugin.json` `version` (patch minimum) on any change — the
marketplace cache is keyed by version.

## License

MIT. See `LICENSE`.

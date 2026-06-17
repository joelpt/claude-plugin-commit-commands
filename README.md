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

## Install

```bash
claude plugin marketplace add joelpt/joelpt-claude-plugins
claude plugin install commit-commands@joelpt-claude-plugins
```

Then restart Claude Code. Requires read access to the private marketplace repo (`gh auth login`).

## Layout

```text
.claude-plugin/plugin.json   ← plugin manifest
commands/                    ← /commit, /commitall
scripts/                     ← pre-flight determiner (incl. codex resolution)
shared/                      ← shared commit logic
tst/                         ← determiner tests
```

Distributed via the [`joelpt-claude-plugins`](https://github.com/joelpt/joelpt-claude-plugins)
marketplace. Bump `.claude-plugin/plugin.json` `version` (patch minimum) on any change — the
marketplace cache is keyed by version.

## License

MIT. See `LICENSE`.

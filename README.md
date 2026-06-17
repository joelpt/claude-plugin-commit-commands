# commit-commands

Atomic git commits for Claude Code with a code-review + simplify pre-flight, enforcing
project git rules (conventional messages, no `git add -A`, no `--no-verify`, no AI
attribution). Replaces the `claude-plugins-official` commit-commands.

Provides `/commit` (session changes) and `/commitall` (all uncommitted changes).

## Pre-flight review

Before staging, a deterministic gate (`scripts/determine_preflight.py`) measures the changeset (Δloc, complexity, file class, path-sensitivity, git regression-gravity) and picks a review intensity:

- **trivial** (docs/data, semantic no-ops, tiny low-complexity diffs) → no review; commit directly.
- **standard** → `/code-review`.
- **sensitive / complex** → `feature-dev:code-reviewer` + `/code-review` (high on complex), **plus a parallel Codex (GPT-5) second opinion**.

### Codex second opinion

On the sensitive/complex tiers the pre-flight also runs a Codex review via the [OpenAI codex plugin](https://github.com/openai/codex-plugin-cc), invoking its companion script directly because the `/codex:review` slash command is `disable-model-invocation`.
It is launched as a background task so its latency overlaps the other reviewers, then collected before the issues gate.
Codex findings tagged `[P1]`/`[P2]` are auto-fixed (Critical/Important); lower findings are surfaced verbatim.

Requirements and behavior:

- The codex plugin must be installed and authenticated (`codex login` / `/codex:setup`); the pre-flight probes readiness and pauses to ask if it is not ready.
- If the codex plugin is absent, Codex review is skipped silently — it never blocks a commit.
- Auth runs through your OpenAI/Codex plan, not a metered Anthropic API key.
- Opt out by setting `COMMIT_CODEX_REVIEW=0` in the environment.

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
scripts/                     ← pre-flight determiner + codex-path resolver
shared/                      ← shared commit logic
tst/                         ← determiner + resolver tests
```

Distributed via the [`joelpt-claude-plugins`](https://github.com/joelpt/joelpt-claude-plugins)
marketplace. Bump `.claude-plugin/plugin.json` `version` (patch minimum) on any change — the
marketplace cache is keyed by version.

## License

MIT. See `LICENSE`.

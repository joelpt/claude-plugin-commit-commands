# commit-commands

Atomic git commits for Claude Code with a code-review + simplify pre-flight, enforcing
project git rules (conventional messages, no `git add -A`, no `--no-verify`, no AI
attribution). Replaces the `claude-plugins-official` commit-commands.

Provides `/commit` (session changes) and `/commitall` (all uncommitted changes).

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
scripts/                     ← pre-flight + commit helpers
shared/                      ← shared commit logic
```

Distributed via the [`joelpt-claude-plugins`](https://github.com/joelpt/joelpt-claude-plugins)
marketplace. Bump `.claude-plugin/plugin.json` `version` (patch minimum) on any change — the
marketplace cache is keyed by version.

## License

MIT. See `LICENSE`.

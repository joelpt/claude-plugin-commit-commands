# commit-commands Plugin — Development Notes

## Testing the preflight determiner during development

`/commit` and `/commitall` run the preflight script via a `!` bash directive that resolves
`${CLAUDE_PLUGIN_ROOT}` to the **cached** plugin directory (e.g.
`~/.claude/plugins/cache/joelpt-claude-plugins/commit-commands/<version>/`), not the working directory.

This means edits to `scripts/determine_preflight.py` are invisible to `/commit` until
you publish a new version and run `claude plugin marketplace update`.

When you need to verify the working-directory variant of the script — after changing
complexity thresholds, adding a sensitivity pattern, tweaking step text, etc. — run it
directly from the repo root:

```bash
uv run scripts/determine_preflight.py
```

The `uv` inline deps (complexipy, lizard) are declared in the script header; `uv` installs
them into `~/.cache/uv` on first run and reuses the cache thereafter.

## Commit-enforcement permissions-grant mechanism

The enforce gate (`hooks/enforce_commit_commands_hook.py`) authorizes a `git commit` only
when the current session holds a valid **permissions grant**, minted by `/commit` / `/commitall`
via a `!` context directive that runs `scripts/commit_grant.py grant`. The grant is a
short-lived, session-scoped lease keyed by `CLAUDE_CODE_SESSION_ID`, stored under
`~/.config/commit-commands/grants/<session>.json`.

Design constraints worth keeping in mind when editing:

- **`commit_grant.py` is pure stdlib (argparse, no typer).** The hook imports it under a
  bare `python3` (no `uv`), so a third-party dep would risk bricking commits on import. The
  typer-based `commit_config.py` is fine because nothing imports it — it's only ever a CLI.
- **The grant is a lease, not single-use.** A `/commitall` run makes several atomic commits
  under one grant, so the hook must not consume the grant on read — only the TTL expires it.
- **The grant directive lives in the top-level command files, not `shared/commit-workflow.md`.**
  `${CLAUDE_PLUGIN_ROOT}` is **not** substituted inside `@`-included files, so a grant
  directive there would not resolve. `commit.md` / `commitall.md` are the only place it works.
- The TTL defaults to 300s; `commit_grant_ttl_seconds` in the config widens it for flows
  whose review/HITL pauses might otherwise outlast the grant.

### The `grant-commit-privileges` escape hatch

`commands/grant-commit-privileges.md` is the sanctioned way to mint a permissions grant when a
commit *cannot* go through `/commit(all)` (escaping edge cases, a batch `--no-verify` commit tool,
cross-repo commits). It is a two-phase, model-driven opt-in: the command body explains the
valid/invalid cases and **only** mints the grant when re-invoked with a non-empty
`--legitimate-reason`, which the model passes through to `commit_grant.py grant
--legitimate-reason …` (the reason is stored in the grant JSON for an audit trail). The grant
is a body Bash step, not a `!` context directive, precisely so it can be conditional — a context
directive would fire unconditionally at invocation.

Frontmatter is intentionally just the one-line `description`; the gating logic lives in the body
so the model discovers the conditions at point of use rather than being handed a bypass.

Run the tests (pytest for grant + hook, standalone script for the determiner):

```bash
just test
```

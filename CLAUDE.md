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

## Commit-enforcement credit mechanism

The enforce gate (`hooks/enforce_commit_commands_hook.py`) authorizes a `git commit` only
when the current session holds a valid **commit credit**, minted by `/commit` / `/commitall`
via a `!` context directive that runs `scripts/commit_credit.py grant`. The credit is a
short-lived, session-scoped lease keyed by `CLAUDE_CODE_SESSION_ID`, stored under
`~/.config/commit-commands/credits/<session>.json`.

Design constraints worth keeping in mind when editing:

- **`commit_credit.py` is pure stdlib (argparse, no typer).** The hook imports it under a
  bare `python3` (no `uv`), so a third-party dep would risk bricking commits on import. The
  typer-based `commit_config.py` is fine because nothing imports it — it's only ever a CLI.
- **The credit is a lease, not single-use.** A `/commitall` run makes several atomic commits
  under one grant, so the hook must not consume the credit on read — only the TTL expires it.
- **Grant lives in the top-level command files, not `shared/commit-workflow.md`.**
  `${CLAUDE_PLUGIN_ROOT}` is **not** substituted inside `@`-included files, so a grant
  directive there would not resolve. `commit.md` / `commitall.md` are the only place it works.
- The TTL defaults to 300s; `commit_credit_ttl_seconds` in the config widens it for flows
  whose review/HITL pauses might otherwise outlast the credit.

Run the tests (pytest for credit + hook, standalone script for the determiner):

```bash
just test
```

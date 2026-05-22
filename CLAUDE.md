# commit-commands Plugin — Development Notes

## Testing the preflight determiner during development

`/commit` and `/commitall` run the preflight script via a `!` bash directive that resolves
`${CLAUDE_PLUGIN_ROOT}` to the **cached** plugin directory (e.g.
`~/.claude/plugins/cache/joelpt-claude-plugins/commit-commands/<version>/`), not the working directory.

This means edits to `scripts/determine-preflight.py` are invisible to `/commit` until
you publish a new version and run `claude plugin marketplace update`.

When you need to verify the working-directory variant of the script — after changing
complexity thresholds, adding a sensitivity pattern, tweaking step text, etc. — run it
directly from the repo root:

```bash
uv run scripts/determine-preflight.py
```

The `uv` inline deps (complexipy, lizard) are declared in the script header; `uv` installs
them into `~/.cache/uv` on first run and reuses the cache thereafter.

---
description: Grant temporary allowance to call 'git commit' directly
---

`/commit` and `/commitall` are the ONLY sanctioned commit paths. They run the
preflight review, enforce message hygiene, and mint the short-lived permissions
grant that lets the enforce gate pass. **Always prefer them.** This command exists
only for the rare case where you *strictly cannot* route a commit through `/commit(all)`.

It opens a ~5-minute, session-scoped window in which raw `git commit` calls are
allowed — the same permissions grant `/commit(all)` mints, granted directly. Use it sparingly.

## NOT legitimate — do not grant for these

- You hit a **pre-commit hook** failure and want to skip it. Standing guidance is to
  run pre-commit hooks, never bypass them — fix the failure instead.
- You'd simply **rather not** go through the `/commit(all)` review flow. Convenience
  is not a reason.
- A normal in-session commit that `/commit` or `/commitall` could handle perfectly well.

## Legitimate — a grant is justified

- You must issue a raw `git commit` directly because of **character-escaping / quoting**
  that the `/commit(all)` tool path cannot express.
- Another **sanctioned skill's documented pattern** requires calling `git commit` directly
  — e.g. a batch tool that makes retroactive `--no-verify` commits across many sibling repos
  that `/commit` structurally cannot reach.
- Committing in a **repo other than this session's cwd**, where `/commit(all)` cannot operate.

## What to do now

You invoked this command with arguments: `$ARGUMENTS`

- **If no non-empty `--legitimate-reason` is present above:** do NOT grant anything, and do
  NOT run any script. Re-read the cases above. Only if a genuinely justified case applies,
  invoke this command again with your reason:

  `/commit-commands:grant-commit-privileges --legitimate-reason "<why you cannot use /commit(all)>"`

  If you do not have a justified reason, STOP and tell the user you are blocked and why —
  do not work around the gate by any other means.

- **If a non-empty `--legitimate-reason "<reason>"` IS present:** mint the permissions grant
  now by running exactly this, substituting the reason verbatim:

  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/commit_grant.py" grant --legitimate-reason "<reason>"
  ```

  Then tell the user, in one line, that a ~5-minute unrestricted `git commit` window is open
  for this session and restate the recorded reason. Proceed with the specific commit(s) you
  were blocked on — nothing more.

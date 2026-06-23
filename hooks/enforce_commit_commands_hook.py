"""PreToolUse hook: deny raw git commit, redirect to /commit or /commitall.

Blocks Bash tool calls that invoke ``git commit`` directly, enforcing the
CLAUDE.md policy that ``/commit`` or ``/commitall`` is the ONLY sanctioned
commit path (they enforce preflight, the code-review gate, and message hygiene).

A commit is allowed only when the current Claude session holds a valid
*permissions grant* (see ``scripts/commit_grant.py``). ``/commit`` and
``/commitall`` mint that grant when invoked, via a ``!`` context directive that
runs ``commit_grant.py grant``. The session id ties the grant to one session
(``session_id`` from the hook payload == ``CLAUDE_CODE_SESSION_ID`` in the
granting shell), and a short TTL bounds its lifetime.

This replaces the old ``∴ committed ∴`` sentinel, which the model could forge by
simply echoing the phrase after a raw commit. There is no longer a magic string
to append: authorization lives in out-of-band per-session state that only the
sanctioned command flow mints.

Config (``~/.config/commit-commands/config.json``):
    enforce_commit_commands_use (bool, default true): set to false to disable.
    commit_grant_ttl_seconds (int, default 300): permissions-grant lifetime.

Exit codes:
    0 — allow (not a commit, or granted, or enforcement disabled)
    2 — block (unsanctioned raw git commit)
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "commit-commands" / "config.json"

_PLUGIN_ROOT = os.environ.get("CLAUDE_PLUGIN_ROOT")
_SCRIPTS_DIR = (
    Path(_PLUGIN_ROOT) / "scripts"
    if _PLUGIN_ROOT
    else Path(__file__).resolve().parent.parent / "scripts"
)
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

try:
    import commit_grant  # noqa: E402  -- sibling module, path bootstrapped above

    _import_error: BaseException | None = None
except Exception as exc:  # noqa: BLE001  -- a broken import must not brick commits
    commit_grant = None  # type: ignore[assignment]
    _import_error = exc

BLOCK_MESSAGE = (
    "BLOCKED: raw `git commit` is not allowed — no permissions grant for this session.\n"
    "\n"
    "Policy (CLAUDE.md): /commit and /commitall are the ONLY sanctioned commit\n"
    "paths — they enforce preflight, the code-review gate, and message hygiene.\n"
    "They mint a short-lived, session-scoped permissions grant that lets this gate\n"
    "pass; a raw `git commit` outside that flow has no grant and is blocked.\n"
    "\n"
    "What to do instead — almost always:\n"
    "  • Normal session commit  → /commit or /commitall\n"
    "\n"
    "Only if /commit / /commitall genuinely CANNOT do the job — character-escaping\n"
    "the tool path can't express, another sanctioned skill's documented `git commit`\n"
    "pattern (e.g. a batch `--no-verify` commit tool), or a commit in a repo other\n"
    "than this session's cwd — open a short, session-scoped window with the opt-in:\n"
    "\n"
    '  /commit-commands:grant-commit-privileges --legitimate-reason "<why /commit(all) cannot be used>"\n'
    "\n"
    "It mints the grant ONLY with an explicit, justified reason. NOT legitimate:\n"
    "skipping a pre-commit hook, or simply not wanting the review flow. If you have\n"
    "no justified reason, STOP and tell the user you are blocked and why — do NOT\n"
    "hack around this gate by any other means.\n"
    "\n"
    "To disable this enforcement entirely:  /commit-config"
)


def _enforcement_enabled() -> bool:
    """Return True when enforcement is active (default when config absent)."""
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return bool(cfg.get("enforce_commit_commands_use", True))
    except Exception:  # noqa: BLE001
        return True


def main() -> None:
    """Check the Bash command for an unsanctioned git commit and block if found."""
    try:
        data: dict = json.load(sys.stdin)
    except Exception:  # noqa: BLE001
        sys.exit(0)

    if data.get("tool_name") != "Bash":
        sys.exit(0)

    if not _enforcement_enabled():
        sys.exit(0)

    command: str = data.get("tool_input", {}).get("command", "")

    # Negative lookahead (?![-_/]) excludes filename fragments like
    # commit-config.md, commit_config.py, commit/whatever — ensuring we only
    # match `commit` as a git subcommand, not as part of a path argument.
    if not re.search(r"\bgit\b[^|;&\n]*\bcommit(?![-_/])", command):
        sys.exit(0)

    # Allow read-only help invocations.
    commit_tail = re.split(r"\bcommit\b", command, maxsplit=1)[-1].strip()
    if commit_tail.startswith(("--help", "-h")):
        sys.exit(0)

    # A broken grant module must not brick committing globally: fail open, but
    # leave a diagnostic (visible only in the debug log on exit 0). Near-impossible
    # in practice — commit_grant is pure stdlib.
    if commit_grant is None:
        sys.stderr.write(
            f"commit-commands: grant module failed to import ({_import_error!r}); "
            "enforcement is failing OPEN.\n"
        )
        sys.exit(0)

    session_id = data.get("session_id") or os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if commit_grant.is_authorized(session_id):
        sys.exit(0)

    print(BLOCK_MESSAGE, file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()

"""PreToolUse hook: deny raw git commit, redirect to /commit or /commitall.

Blocks Bash tool calls that invoke ``git commit`` directly, enforcing the
CLAUDE.md policy that ``/commit`` or ``/commitall`` is the ONLY sanctioned
commit path (they enforce preflight, the code-review gate, and message hygiene).

A commit is allowed only when the current Claude session holds a valid *commit
credit* (see ``scripts/commit_credit.py``). ``/commit`` and ``/commitall`` mint
that credit when invoked, via a ``!`` context directive that runs
``commit_credit.py grant``. The session id ties the credit to one session
(``session_id`` from the hook payload == ``CLAUDE_CODE_SESSION_ID`` in the
granting shell), and a short TTL bounds its lifetime.

This replaces the old ``∴ committed ∴`` sentinel, which the model could forge by
simply echoing the phrase after a raw commit. There is no longer a magic string
to append: authorization lives in out-of-band per-session state that only the
sanctioned command flow mints.

Config (``~/.config/commit-commands/config.json``):
    enforce_commit_commands_use (bool, default true): set to false to disable.
    commit_credit_ttl_seconds (int, default 300): credit lifetime.

Exit codes:
    0 — allow (not a commit, or credited, or enforcement disabled)
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
    import commit_credit  # noqa: E402  -- sibling module, path bootstrapped above

    _import_error: BaseException | None = None
except Exception as exc:  # noqa: BLE001  -- a broken import must not brick commits
    commit_credit = None  # type: ignore[assignment]
    _import_error = exc

BLOCK_MESSAGE = (
    "BLOCKED: raw `git commit` is not allowed — no commit credit for this session.\n"
    "\n"
    "Policy (CLAUDE.md): /commit and /commitall are the ONLY sanctioned commit\n"
    "paths — they enforce preflight, the code-review gate, and message hygiene.\n"
    "They mint a short-lived, session-scoped commit credit that lets this gate\n"
    "pass; a raw `git commit` outside that flow has no credit and is blocked.\n"
    "\n"
    "What to do instead:\n"
    "  • Normal session commit  → /commit or /commitall\n"
    "  • Sibling-repo commit     → run in your terminal:  ! git -C <path> commit …\n"
    "    (the ! prefix routes it through your shell, not the Bash tool)\n"
    "\n"
    "If /commit / /commitall cannot accomplish your commit goal here, STOP and\n"
    "tell the user what is happening — do NOT try to hack around this gate.\n"
    "\n"
    "To disable this enforcement:  /commit-config"
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

    # A broken credit module must not brick committing globally: fail open, but
    # leave a diagnostic (visible only in the debug log on exit 0). Near-impossible
    # in practice — commit_credit is pure stdlib.
    if commit_credit is None:
        sys.stderr.write(
            f"commit-commands: credit module failed to import ({_import_error!r}); "
            "enforcement is failing OPEN.\n"
        )
        sys.exit(0)

    session_id = data.get("session_id") or os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if commit_credit.is_authorized(session_id):
        sys.exit(0)

    print(BLOCK_MESSAGE, file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()

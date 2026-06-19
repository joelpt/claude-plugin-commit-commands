"""PreToolUse hook: deny raw git commit, redirect to /commit or /commitall.

Blocks Bash tool calls that invoke ``git commit`` directly, enforcing the
CLAUDE.md policy that ``/commit`` or ``/commitall`` is the ONLY sanctioned
commit path (they enforce preflight, the code-review gate, and message hygiene).

The sentinel ``∴ committed ∴`` in the command marks a call that originated from
the /commit skill's own commit loop (commit-workflow.md always chains:
``git commit -m "..." && git log -1 --stat && echo '∴ committed ∴'``).
The full phrase (not just ``∴``) avoids false-passes on commit messages or
filenames that happen to contain the THEREFORE symbol.

Config (``~/.config/commit-commands/config.json``):
    enforce_commit_commands_use (bool, default true): set to false to disable.

Exit codes:
    0 — allow (not a commit, or sanctioned, or enforcement disabled)
    2 — block (unsanctioned raw git commit)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SENTINEL = "∴ committed ∴"
CONFIG_PATH = Path.home() / ".config" / "commit-commands" / "config.json"


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

    # Allow the /commit skill's sanctioned pattern: commit-workflow.md always
    # chains the sentinel phrase after git log.
    if SENTINEL in command:
        sys.exit(0)

    print(
        "BLOCKED: raw `git commit` is not allowed.\n"
        "\n"
        "Policy (CLAUDE.md): /commit and /commitall are the ONLY sanctioned commit\n"
        "paths — they enforce preflight, the code-review gate, and message hygiene.\n"
        "\n"
        "What to do instead:\n"
        "  • Normal session commit  → /commit or /commitall\n"
        "  • Sibling-repo commit    → run in your terminal:  ! git -C <path> commit …\n"
        "    (the ! prefix routes it through your shell, not the Bash tool)\n"
        "\n"
        "To disable this enforcement:  /commit-config",
        file=sys.stderr,
    )
    sys.exit(2)


if __name__ == "__main__":
    main()

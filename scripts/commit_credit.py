"""Session-scoped git-commit credits for the enforce-commit-commands gate.

The PreToolUse enforce hook blocks raw ``git commit`` unless the current Claude
session holds a valid *commit credit*. A credit is minted when the session
invokes ``/commit`` or ``/commitall``: a ``!`` context directive in those
commands runs :func:`grant`, which records a per-session credit that authorizes
git commits until it expires (``CREDIT_TTL_SECONDS``).

This replaces the old, easily-forged ``∴ committed ∴`` sentinel. There is no
longer a magic string to append to a commit line, so the model cannot bypass the
gate by echoing a token: a credit can exist only if the sanctioned command flow
actually ran in this session, and it evaporates on its own after the TTL.

A credit is a short-lived *lease*, not a single-use token. One ``/commitall`` run
can produce several atomic commits; a single grant covers all of them, with
staleness bounded by the TTL rather than by consumption. The TTL can be widened
(``commit_credit_ttl_seconds`` in the config) for flows whose review/HITL pauses
might otherwise outlast it.

Credits are keyed by the Claude session id -- ``CLAUDE_CODE_SESSION_ID`` for the
granting CLI caller, the ``session_id`` payload field for the hook; the harness
keeps the two equal -- so a credit minted in one session never authorizes a
commit in another.

Pure standard library on purpose: the enforce hook imports this module under a
bare ``python3`` (no ``uv``, no third-party deps), so a missing package can never
break commit enforcement.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "commit-commands" / "config.json"
CREDITS_DIR = Path.home() / ".config" / "commit-commands" / "credits"
CREDIT_TTL_SECONDS = 300
_TTL_CONFIG_KEY = "commit_credit_ttl_seconds"
_NO_SESSION_KEY = "_nosession"
_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_.-]")


def _ttl_seconds() -> int:
    """Return the credit lifetime in seconds (config override or default)."""
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        ttl = cfg.get(_TTL_CONFIG_KEY)
        if isinstance(ttl, int) and not isinstance(ttl, bool) and ttl > 0:
            return ttl
    except Exception:  # noqa: BLE001
        pass
    return CREDIT_TTL_SECONDS


def _safe_session_id(session_id: str) -> str:
    """Sanitize a session id into a filename-safe token.

    Args:
        session_id: The raw session id (may be empty).

    Returns:
        A filename-safe token, or a shared fallback key when empty.
    """
    cleaned = _SAFE_ID_RE.sub("", session_id)[:64]
    return cleaned or _NO_SESSION_KEY


def resolve_session_id(explicit: str | None = None) -> str:
    """Resolve the session id from an explicit value or the environment.

    Args:
        explicit: A session id passed directly (e.g. ``--session``); takes
            precedence over the environment when non-empty.

    Returns:
        The resolved session id, or an empty string when none is available.
    """
    return explicit or os.environ.get("CLAUDE_CODE_SESSION_ID", "")


def _credit_path(session_id: str) -> Path:
    """Return the credit file path for a (possibly empty) session id."""
    return CREDITS_DIR / f"{_safe_session_id(session_id)}.json"


def _safe_unlink(path: Path) -> None:
    """Remove a credit file, ignoring a missing file or OS error."""
    try:
        path.unlink()
    except OSError:
        pass


def grant(session_id: str, *, now: float | None = None, ttl: int | None = None) -> Path:
    """Mint a commit credit for a session.

    Args:
        session_id: The Claude session id (empty falls back to a shared key).
        now: Epoch seconds to stamp the grant (defaults to the wall clock).
        ttl: Lifetime in seconds (defaults to the configured/standard TTL).

    Returns:
        The path of the written credit file.
    """
    stamp = time.time() if now is None else now
    lifetime = _ttl_seconds() if ttl is None else ttl
    path = _credit_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps({"granted_at": stamp, "expires_at": stamp + lifetime}) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)
    return path


def is_authorized(session_id: str, *, now: float | None = None) -> bool:
    """Return whether the session holds a valid (non-expired) commit credit.

    A valid credit is a lease: it is not consumed on read, so consecutive commits
    in one sanctioned run all pass. An expired or corrupt credit is removed as a
    side effect of the check.

    Args:
        session_id: The Claude session id to check.
        now: Epoch seconds to compare against (defaults to the wall clock).

    Returns:
        True when a non-expired credit exists for the session.
    """
    moment = time.time() if now is None else now
    path = _credit_path(session_id)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return False
    except Exception:  # noqa: BLE001
        _safe_unlink(path)
        return False
    expires_at = data.get("expires_at")
    if not isinstance(expires_at, (int, float)) or isinstance(expires_at, bool):
        _safe_unlink(path)
        return False
    if expires_at <= moment:
        _safe_unlink(path)
        return False
    return True


def clear(session_id: str) -> None:
    """Remove any commit credit held by a session."""
    _safe_unlink(_credit_path(session_id))


def _build_parser() -> argparse.ArgumentParser:
    """Construct the argparse CLI for credit management."""
    parser = argparse.ArgumentParser(
        prog="commit_credit.py",
        description="Manage session-scoped git-commit credits.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, help_text in (
        ("grant", "Mint a commit credit for the session."),
        ("status", "Report whether a valid credit exists (exit 0 if so)."),
        ("clear", "Remove the session's credit."),
    ):
        child = sub.add_parser(name, help=help_text)
        child.add_argument(
            "--session",
            default=None,
            help="Session id (default: $CLAUDE_CODE_SESSION_ID).",
        )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the credit CLI.

    Args:
        argv: Argument vector (defaults to ``sys.argv[1:]``).

    Returns:
        A process exit code.
    """
    args = _build_parser().parse_args(argv)
    session_id = resolve_session_id(args.session)
    if args.cmd == "grant":
        grant(session_id)
        print(
            f"commit credit granted for session {_safe_session_id(session_id)} "
            f"(valid {_ttl_seconds()}s)"
        )
        return 0
    if args.cmd == "status":
        ok = is_authorized(session_id)
        print("valid" if ok else "none")
        return 0 if ok else 1
    clear(session_id)
    print("cleared")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Integration tests for the enforce-commit-commands PreToolUse hook.

The hook is exercised as a subprocess (the way Claude Code runs it) with an
isolated ``HOME`` so the grant store and config resolve under a tmp dir. A
permissions grant is minted by invoking ``commit_grant.py grant`` with the same
isolated ``HOME`` and a session id, then the hook is fed a matching Bash payload.

Exit-code contract: 0 = allow, 2 = block.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_HOOK = _ROOT / "hooks" / "enforce_commit_commands_hook.py"
_GRANT = _ROOT / "scripts" / "commit_grant.py"


def _env(home: Path) -> dict[str, str]:
    """Build a subprocess env rooted at an isolated HOME, no inherited session id."""
    return {"HOME": str(home), "PATH": "/usr/bin:/bin"}


def _grant(home: Path, session_id: str) -> None:
    """Mint a permissions grant for a session under the isolated HOME."""
    proc = subprocess.run(
        [sys.executable, str(_GRANT), "grant", "--session", session_id],
        env=_env(home),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


def _run_hook(home: Path, payload: dict[str, object]) -> subprocess.CompletedProcess[str]:
    """Run the hook subprocess with a JSON payload on stdin."""
    return subprocess.run(
        [sys.executable, str(_HOOK)],
        input=json.dumps(payload),
        env=_env(home),
        capture_output=True,
        text=True,
    )


def _bash_payload(command: str, session_id: str = "sess-a") -> dict[str, object]:
    """Construct a PreToolUse Bash payload."""
    return {
        "tool_name": "Bash",
        "session_id": session_id,
        "tool_input": {"command": command},
    }


def test_non_bash_tool_is_allowed(tmp_path: Path) -> None:
    """Non-Bash tools are never the hook's concern."""
    proc = _run_hook(tmp_path, {"tool_name": "Edit", "tool_input": {}})
    assert proc.returncode == 0


def test_non_commit_bash_is_allowed(tmp_path: Path) -> None:
    """A Bash call that is not a git commit passes untouched."""
    proc = _run_hook(tmp_path, _bash_payload("git status"))
    assert proc.returncode == 0


def test_raw_commit_without_grant_is_blocked(tmp_path: Path) -> None:
    """A raw git commit with no grant for the session is blocked."""
    proc = _run_hook(tmp_path, _bash_payload('git commit -m "x"'))
    assert proc.returncode == 2
    assert "BLOCKED" in proc.stderr
    assert "grant-commit-privileges" in proc.stderr
    assert "--legitimate-reason" in proc.stderr


def test_raw_commit_with_grant_is_allowed(tmp_path: Path) -> None:
    """A git commit is allowed once the session holds a valid grant."""
    _grant(tmp_path, "sess-a")
    proc = _run_hook(tmp_path, _bash_payload('git commit -m "x"', "sess-a"))
    assert proc.returncode == 0


def test_grant_is_session_scoped(tmp_path: Path) -> None:
    """A grant minted for one session does not authorize another's commit."""
    _grant(tmp_path, "sess-a")
    proc = _run_hook(tmp_path, _bash_payload('git commit -m "x"', "sess-b"))
    assert proc.returncode == 2


def test_multiple_commits_under_one_grant(tmp_path: Path) -> None:
    """The grant is a lease: several commits in one run all pass on one grant."""
    _grant(tmp_path, "sess-a")
    for _ in range(3):
        proc = _run_hook(tmp_path, _bash_payload('git commit -m "x"', "sess-a"))
        assert proc.returncode == 0


def test_commit_help_is_allowed(tmp_path: Path) -> None:
    """`git commit --help` is read-only and never blocked."""
    proc = _run_hook(tmp_path, _bash_payload("git commit --help"))
    assert proc.returncode == 0


def test_filename_false_positive_is_allowed(tmp_path: Path) -> None:
    """A path fragment like commit-config.md must not trip the commit matcher."""
    proc = _run_hook(tmp_path, _bash_payload("cat commit-config.md"))
    assert proc.returncode == 0


def test_enforcement_disabled_allows_raw_commit(tmp_path: Path) -> None:
    """With enforcement disabled in config, raw commits pass with no grant."""
    cfg = tmp_path / ".config" / "commit-commands" / "config.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps({"enforce_commit_commands_use": False}), encoding="utf-8")
    proc = _run_hook(tmp_path, _bash_payload('git commit -m "x"'))
    assert proc.returncode == 0


def test_expired_grant_is_blocked(tmp_path: Path) -> None:
    """A grant past its TTL no longer authorizes a commit."""
    cfg = tmp_path / ".config" / "commit-commands" / "config.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps({"commit_grant_ttl_seconds": 1}), encoding="utf-8")
    _grant(tmp_path, "sess-a")
    import time

    time.sleep(1.1)
    proc = _run_hook(tmp_path, _bash_payload('git commit -m "x"', "sess-a"))
    assert proc.returncode == 2


@pytest.mark.parametrize("variant", ["git commit", "git -C /repo commit -m m", "git   commit"])
def test_commit_variants_blocked_without_grant(tmp_path: Path, variant: str) -> None:
    """Assorted real git-commit spellings are all gated."""
    proc = _run_hook(tmp_path, _bash_payload(variant))
    assert proc.returncode == 2

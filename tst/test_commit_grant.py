#!/usr/bin/env python3
"""Unit tests for session-scoped commit-permissions grants (commit_grant.py).

Time is injected via the ``now=`` parameter rather than frozen, so these tests
need no clock-mocking dependency. The grant store and config path are redirected
onto a tmp dir per test so nothing touches the real ``~/.config``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import commit_grant as cg


@pytest.fixture(autouse=True)
def _isolate_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect the grant store and config onto a temp directory."""
    monkeypatch.setattr(cg, "GRANTS_DIR", tmp_path / "grants")
    monkeypatch.setattr(cg, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)


def test_grant_then_authorized_within_ttl() -> None:
    """A freshly minted grant authorizes commits before it expires."""
    cg.grant("sess-a", now=1000.0)
    assert cg.is_authorized("sess-a", now=1000.0) is True
    assert cg.is_authorized("sess-a", now=1000.0 + cg.GRANT_TTL_SECONDS - 1) is True


def test_grant_expires_after_ttl() -> None:
    """A grant is rejected (and removed) once its TTL has elapsed."""
    cg.grant("sess-a", now=1000.0)
    assert cg.is_authorized("sess-a", now=1000.0 + cg.GRANT_TTL_SECONDS + 1) is False
    assert not cg._grant_path("sess-a").exists()


def test_grant_is_a_lease_not_single_use() -> None:
    """Reading a valid grant does not consume it; repeat commits all pass."""
    cg.grant("sess-a", now=1000.0)
    assert cg.is_authorized("sess-a", now=1001.0) is True
    assert cg.is_authorized("sess-a", now=1002.0) is True
    assert cg._grant_path("sess-a").exists()


def test_sessions_are_isolated() -> None:
    """A grant for one session never authorizes another."""
    cg.grant("sess-a", now=1000.0)
    assert cg.is_authorized("sess-b", now=1000.0) is False


def test_absent_grant_is_unauthorized() -> None:
    """A session with no grant file is not authorized."""
    assert cg.is_authorized("nobody", now=1000.0) is False


def test_clear_removes_grant() -> None:
    """clear() revokes a session's grant."""
    cg.grant("sess-a", now=1000.0)
    cg.clear("sess-a")
    assert cg.is_authorized("sess-a", now=1000.0) is False


def test_corrupt_grant_is_rejected_and_removed() -> None:
    """A malformed grant file is treated as no grant and cleaned up."""
    path = cg._grant_path("sess-a")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json", encoding="utf-8")
    assert cg.is_authorized("sess-a", now=1000.0) is False
    assert not path.exists()


def test_missing_expires_field_is_rejected() -> None:
    """A grant lacking a numeric expires_at is rejected."""
    path = cg._grant_path("sess-a")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"granted_at": 1000.0}), encoding="utf-8")
    assert cg.is_authorized("sess-a", now=1000.0) is False


def test_ttl_config_override(tmp_path: Path) -> None:
    """A positive integer config override widens the grant lifetime."""
    (tmp_path / "config.json").write_text(
        json.dumps({"commit_grant_ttl_seconds": 1800}), encoding="utf-8"
    )
    cg.grant("sess-a", now=1000.0)
    assert cg.is_authorized("sess-a", now=1000.0 + 1700) is True
    assert cg.is_authorized("sess-a", now=1000.0 + 1900) is False


def test_ttl_config_ignores_bad_values(tmp_path: Path) -> None:
    """Non-positive or non-int TTL overrides fall back to the default."""
    (tmp_path / "config.json").write_text(
        json.dumps({"commit_grant_ttl_seconds": True}), encoding="utf-8"
    )
    assert cg._ttl_seconds() == cg.GRANT_TTL_SECONDS


def test_resolve_session_id_prefers_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit session id wins over the environment; env is the fallback."""
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "from-env")
    assert cg.resolve_session_id("explicit") == "explicit"
    assert cg.resolve_session_id(None) == "from-env"


def test_grant_records_reason_when_given() -> None:
    """A legitimate-reason is persisted in the grant and does not block validity."""
    path = cg.grant("sess-a", now=1000.0, reason="batch version-bump commits")
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["reason"] == "batch version-bump commits"
    assert cg.is_authorized("sess-a", now=1001.0) is True


def test_grant_omits_reason_key_when_absent() -> None:
    """A reasonless grant (the /commit path) writes no reason key."""
    path = cg.grant("sess-a", now=1000.0)
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert "reason" not in stored


def test_grant_cli_legitimate_reason(capsys: pytest.CaptureFixture[str]) -> None:
    """The CLI grant accepts --legitimate-reason and echoes it back."""
    rc = cg.main(["grant", "--session", "sess-a", "--legitimate-reason", "escaping issue"])
    assert rc == 0
    assert "escaping issue" in capsys.readouterr().out
    assert cg.is_authorized("sess-a") is True


def test_empty_session_uses_shared_fallback_key() -> None:
    """An empty session id maps to the shared fallback key consistently."""
    cg.grant("", now=1000.0)
    assert cg.is_authorized("", now=1000.0) is True
    assert cg._grant_path("").name == f"{cg._NO_SESSION_KEY}.json"

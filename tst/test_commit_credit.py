#!/usr/bin/env python3
"""Unit tests for session-scoped commit credits (commit_credit.py).

Time is injected via the ``now=`` parameter rather than frozen, so these tests
need no clock-mocking dependency. The credit store and config path are
redirected onto a tmp dir per test so nothing touches the real ``~/.config``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import commit_credit as cc


@pytest.fixture(autouse=True)
def _isolate_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect the credit store and config onto a temp directory."""
    monkeypatch.setattr(cc, "CREDITS_DIR", tmp_path / "credits")
    monkeypatch.setattr(cc, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)


def test_grant_then_authorized_within_ttl() -> None:
    """A freshly granted credit authorizes commits before it expires."""
    cc.grant("sess-a", now=1000.0)
    assert cc.is_authorized("sess-a", now=1000.0) is True
    assert cc.is_authorized("sess-a", now=1000.0 + cc.CREDIT_TTL_SECONDS - 1) is True


def test_credit_expires_after_ttl() -> None:
    """A credit is rejected (and removed) once its TTL has elapsed."""
    cc.grant("sess-a", now=1000.0)
    assert cc.is_authorized("sess-a", now=1000.0 + cc.CREDIT_TTL_SECONDS + 1) is False
    assert not cc._credit_path("sess-a").exists()


def test_credit_is_a_lease_not_single_use() -> None:
    """Reading a valid credit does not consume it; repeat commits all pass."""
    cc.grant("sess-a", now=1000.0)
    assert cc.is_authorized("sess-a", now=1001.0) is True
    assert cc.is_authorized("sess-a", now=1002.0) is True
    assert cc._credit_path("sess-a").exists()


def test_sessions_are_isolated() -> None:
    """A credit for one session never authorizes another."""
    cc.grant("sess-a", now=1000.0)
    assert cc.is_authorized("sess-b", now=1000.0) is False


def test_absent_credit_is_unauthorized() -> None:
    """A session with no credit file is not authorized."""
    assert cc.is_authorized("nobody", now=1000.0) is False


def test_clear_removes_credit() -> None:
    """clear() revokes a session's credit."""
    cc.grant("sess-a", now=1000.0)
    cc.clear("sess-a")
    assert cc.is_authorized("sess-a", now=1000.0) is False


def test_corrupt_credit_is_rejected_and_removed() -> None:
    """A malformed credit file is treated as no credit and cleaned up."""
    path = cc._credit_path("sess-a")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json", encoding="utf-8")
    assert cc.is_authorized("sess-a", now=1000.0) is False
    assert not path.exists()


def test_missing_expires_field_is_rejected() -> None:
    """A credit lacking a numeric expires_at is rejected."""
    path = cc._credit_path("sess-a")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"granted_at": 1000.0}), encoding="utf-8")
    assert cc.is_authorized("sess-a", now=1000.0) is False


def test_ttl_config_override(tmp_path: Path) -> None:
    """A positive integer config override widens the credit lifetime."""
    (tmp_path / "config.json").write_text(
        json.dumps({"commit_credit_ttl_seconds": 1800}), encoding="utf-8"
    )
    cc.grant("sess-a", now=1000.0)
    assert cc.is_authorized("sess-a", now=1000.0 + 1700) is True
    assert cc.is_authorized("sess-a", now=1000.0 + 1900) is False


def test_ttl_config_ignores_bad_values(tmp_path: Path) -> None:
    """Non-positive or non-int TTL overrides fall back to the default."""
    (tmp_path / "config.json").write_text(
        json.dumps({"commit_credit_ttl_seconds": True}), encoding="utf-8"
    )
    assert cc._ttl_seconds() == cc.CREDIT_TTL_SECONDS


def test_resolve_session_id_prefers_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit session id wins over the environment; env is the fallback."""
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "from-env")
    assert cc.resolve_session_id("explicit") == "explicit"
    assert cc.resolve_session_id(None) == "from-env"


def test_empty_session_uses_shared_fallback_key() -> None:
    """An empty session id maps to the shared fallback key consistently."""
    cc.grant("", now=1000.0)
    assert cc.is_authorized("", now=1000.0) is True
    assert cc._credit_path("").name == f"{cc._NO_SESSION_KEY}.json"

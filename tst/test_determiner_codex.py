#!/usr/bin/env python3
"""Unit tests for Codex-review step emission in determine_preflight.py.

The determiner imports cleanly under plain python3: complexipy/lizard are
imported lazily inside measure_complexity(), so decide()/measure_sensitivity()
run without uv or those deps. We assert the determiner emits a "run codex review"
step exactly on the escalated tiers (sensitive/complex), never on trivial, and
that COMMIT_CODEX_REVIEW=0 suppresses it. The flag is read inside decide() at
call time, so toggling os.environ between cases needs no re-import.
"""
from __future__ import annotations

import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import determine_preflight as dp  # noqa: E402  -- sibling module on sys.path


def has_codex(steps: list[str]) -> bool:
    """Return whether any step is the Codex-review directive."""
    return any("codex review" in s.lower() for s in steps)


def _index(steps: list[str], needle: str) -> int:
    """Return the index of the first step containing needle, or -1."""
    return next((i for i, s in enumerate(steps) if needle in s.lower()), -1)


def codex_first(steps: list[str]) -> bool:
    """Return whether the Codex step precedes the blocking feature-dev reviewer.

    Codex must be emitted first so executing the steps in order launches it
    (non-blocking, background) before the blocking reviewer, overlapping both.
    """
    ci = _index(steps, "codex review")
    ri = _index(steps, "feature-dev:code-reviewer")
    return ci >= 0 and ri >= 0 and ci < ri


def main() -> int:
    """Run the determiner Codex-step assertions; return 1 on any failure."""
    failures: list[str] = []

    os.environ["COMMIT_CODEX_REVIEW"] = "1"

    c = dp.FileChange(path="src/auth/login.js", added=6, deleted=1,
                      status="M", klass="code")
    dp.measure_sensitivity([c])
    label, steps, *_ = dp.decide([c])
    if label != "sensitive" or not has_codex(steps) or not codex_first(steps):
        failures.append(f"sensitive: label={label} steps={steps}")

    c2 = dp.FileChange(path="src/engine.js", added=500, deleted=0,
                       status="A", klass="code")
    label, steps, *_ = dp.decide([c2])
    if label != "complex" or not has_codex(steps) or not codex_first(steps):
        failures.append(f"complex: label={label} steps={steps}")

    c3 = dp.FileChange(path="src/util.js", added=3, deleted=0,
                       status="M", klass="code")
    label, steps, *_ = dp.decide([c3])
    if label != "trivial" or has_codex(steps):
        failures.append(f"trivial: label={label} steps={steps}")

    os.environ["COMMIT_CODEX_REVIEW"] = "0"
    c4 = dp.FileChange(path="src/auth/login.js", added=6, deleted=1,
                       status="M", klass="code")
    dp.measure_sensitivity([c4])
    label, steps, *_ = dp.decide([c4])
    if has_codex(steps):
        failures.append(f"killswitch: codex still present: {steps}")

    if failures:
        print("FAIL:\n" + "\n".join(failures))
        return 1
    print("PASS: determiner codex-step emission (sensitive, complex, trivial, killswitch)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

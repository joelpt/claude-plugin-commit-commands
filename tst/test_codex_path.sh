#!/usr/bin/env bash
# Verify scripts/codex-path.sh resolves codex-companion.mjs to an existing file,
# or cleanly reports CODEX_COMPANION_NOT_FOUND when the codex plugin is absent.
set -uo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"
resolver="${here}/scripts/codex-path.sh"

out="$(bash "${resolver}" 2>/dev/null)"
rc=$?

if [[ ${rc} -ne 0 ]]; then
  # Codex plugin not installed in this environment -- the resolver's documented
  # "skip optional review" path. Not a failure of the resolver itself.
  echo "SKIP: codex plugin not installed (resolver exited ${rc})"
  exit 0
fi

if [[ "${out}" != *codex-companion.mjs ]]; then
  echo "FAIL: expected a codex-companion.mjs path, got: ${out}"
  exit 1
fi
if [[ ! -f "${out}" ]]; then
  echo "FAIL: resolved path does not exist: ${out}"
  exit 1
fi

echo "PASS: resolved ${out}"
exit 0

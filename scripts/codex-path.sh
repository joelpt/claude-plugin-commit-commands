#!/usr/bin/env bash
# Resolve the path to the OpenAI codex plugin's codex-companion.mjs.
#
# The commit pre-flight runs Codex reviews by invoking this script directly,
# bypassing the /codex:review slash command (which is disable-model-invocation,
# so the model cannot call it). Plugin versions change, so never hardcode a
# versioned path: prefer the version-stable marketplace clone, then fall back to
# the newest cached version.
#
# Prints the absolute path on success (exit 0). Prints CODEX_COMPANION_NOT_FOUND
# to stderr and exits 1 when the codex plugin is not installed -- callers MUST
# treat that as "skip the optional Codex review", never as a hard failure.
set -uo pipefail

root="${HOME}/.claude/plugins"
rel="plugins/codex/scripts/codex-companion.mjs"

stable="${root}/marketplaces/openai-codex/${rel}"
if [[ -f "${stable}" ]]; then
  echo "${stable}"
  exit 0
fi

# Newest cached version, e.g. cache/openai-codex/codex/1.0.4/scripts/...
# Sort version dirs by numeric components -- portable, avoids GNU-only `sort -V`
# (BSD/macOS sort lacks it), so cache-only installs still resolve.
cache_base="${root}/cache/openai-codex/codex"
if [[ -d "${cache_base}" ]]; then
  ver="$(find "${cache_base}" -mindepth 1 -maxdepth 1 -type d -exec basename {} \; 2>/dev/null \
    | sort -t. -k1,1n -k2,2n -k3,3n -k4,4n | tail -n1)"
  cand="${cache_base}/${ver}/scripts/codex-companion.mjs"
  if [[ -n "${ver}" && -f "${cand}" ]]; then
    echo "${cand}"
    exit 0
  fi
fi

echo "CODEX_COMPANION_NOT_FOUND" >&2
exit 1

# commit-commands TODO

## Architecture

Preflight gating (which of code-review / Codex / simplify to run) is decided
**deterministically** by `scripts/determine-preflight.py`, invoked as a `!`
directive in `commands/commit.md` and `commands/commitall.md`. It measures
Δloc, cognitive complexity (Python, complexipy), cyclomatic complexity (other
code, lizard), file classes, path-sensitivity, and git regression-gravity,
then emits the literal preflight steps the shared workflow executes.

The model is used only for the irreducibly-semantic work: commit grouping and
message authorship.

Note: the first `/commit` on a machine with a cold `uv` cache blocks a few
seconds while complexipy + lizard install into `~/.cache/uv`; subsequent runs
are warm. `--quiet` hides the install chatter — not a hang.

## Implemented

- [x] Deterministic preflight determiner (replaces model-judged gating and the
  earlier ad-hoc source-extension skip heuristic)
- [x] Drop eager full `git diff` from command `## Context` — fetch scoped diffs
  on demand; full-tree diff was the dominant per-invocation token cost
- [x] Sensitivity / regression-gravity axis — small changes to auth, migrations,
  CI, hooks, settings, lockfiles, or bug-magnet files escalate despite low loc
- [x] Chain deterministic command pairs in the commit loop to halve round-trips
- [x] Code review via `feature-dev:code-reviewer` (works on the working tree;
  the official `code-review` plugin was PR-only)
- [x] Drop `AskUserQuestion` when reviewer reports zero findings

## Rejected

- [ ] **Cache `git diff` to a tmp file, pass path to reviewer / simplify** —
  `feature-dev:code-reviewer`, `/codex:review`, and `Skill(simplify)` all
  re-derive live git state by design (reviewers need blame/history/context a
  diff snapshot omits; simplify edits real files). A shared snapshot adds a
  staleness invariant for zero orchestrator-token savings, since their
  re-derivation already runs in isolated subagent contexts.

## Deferred (correctness / quality trade-off not worth it)

- [ ] **Run code-reviewer on Haiku** — lower cost but meaningfully lower catch
  rate on subtle bugs and security issues; paying the Sonnet tax is deliberate.

- [ ] **Combine review + simplify into one agent pass** — the two passes catch
  different things: review finds bugs, simplify finds quality/redundancy. One
  pass degrades both.

- [ ] **Cognitive complexity for non-Python code** — complexipy is Python-only;
  other languages use cyclomatic (lizard). A cross-language cognitive metric
  needs a tree-sitter pipeline; not worth it for a Python-primary personal tool.

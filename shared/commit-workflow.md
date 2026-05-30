<!--
Shared workflow body for /commit and /commitall.
Each command supplies its own frontmatter, `## Context` block (with `!` bash
directives — those are NOT parsed inside an @-include), and a `**SCOPE:**`
line defining which changes are "in scope". This file is scope-agnostic and
speaks only of "in-scope changes".
-->

## Steps

DEFINITIONS:
   "call code review": spawn the `feature-dev:code-reviewer` agent via the Agent tool (subagent_type `feature-dev:code-reviewer`) scoped to the in-scope changed files. Show full findings using colorized output and emojis; auto-fix Critical/Important.
   "run code-review": run `Skill("code-review")` on all in-scope code files; auto-fix Critical/Important findings.
   "run code-review high": run `Skill("code-review", "high")` on all in-scope code files; auto-fix Critical/Important findings.

STEPS:

1. The **Preflight determination** in `## Context` is computed deterministically (Δloc, cognitive/cyclomatic complexity, file classes, path-sensitivity, git regression-gravity). **Execute its "Preflight steps to follow" verbatim, in order** — they encode the appropriate review intensity for the changeset. Apply the auto-fix/HITL semantics from DEFINITIONS to each step. Do not re-derive the gating yourself; the determiner has done it.
   - **Fallback** — only if the determination is absent or prints `DETERMINER_UNAVAILABLE`: judge manually — trivial/docs/config/data-only → skip all; complex → call code review + run code-review high; sensitive (not complex) → call code review + run code-review; non-trivial otherwise → run code-review.
2. If the reviewer found **any** issues (Critical, Important, minor, or suggestions): `AskUserQuestion` "Found N issues and M suggestions. Fix any before committing, or proceed?"
3. Perform commit loop, below.

## Commit Loop

Repeat until every in-scope change is committed (out-of-scope changes stay untouched).
Chain the deterministic command pairs to halve round-trips; the only step needing
model inspection is the staged-diff gate between them — never chain across it:

1. `git add <specific files> && git diff --staged` — one call; **inspect** the staged diff output before proceeding.
2. `git commit -m "<<Conventional Commits format message>>" && git log -1 --stat` — one call; confirm.

## Git Rules (IMMUTABLE)

**BANNED:** `git add .`/`-A`/`--all` · `commit -a` · `--no-verify` · AI attribution · emojis · Co-Authored-By · links in messages.

**REQUIRED:** stage by name · `git diff --staged` before every commit · commit only in-scope changes (per the SCOPE above) · message = WHY not WHAT.

**Atomic grouping:** one logical change per commit.
Group if split would break the build (new required param + callsite → same commit).
Split independent changes. Use `git add -p` for partial-file commits.

## Conventional Commits format message

**Format:** `<type>(area): <Subject ≤50 chars, imperative mood, capitalized, no period>` -> strictly adhere to Conventional Commits format
Types: `feat` · `fix` · `docs` · `style` · `refactor` · `perf` · `test` · `chore`
Optional body rules: wrap at 72 chars. Only when needed, write a concise body explaining rationale for this change and/or specifics of the change that would be valuable to a new developer perusing the commit log in the future. Follow best practices for Git commit message bodies.

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
   "run codex review": launch a Codex (GPT-5) second opinion in parallel and merge its findings — see "## Codex Review" below for the full launch/poll/merge protocol.

STEPS:

1. The **Preflight determination** in `## Context` is computed deterministically (Δloc, cognitive/cyclomatic complexity, file classes, path-sensitivity, git regression-gravity). **Execute its "Preflight steps to follow" verbatim, in order** — they encode the appropriate review intensity for the changeset. Apply the auto-fix/HITL semantics from DEFINITIONS to each step. Do not re-derive the gating yourself; the determiner has done it.
   - **Fallback** — only if the determination is absent or prints `DETERMINER_UNAVAILABLE`: judge manually — trivial/docs/config/data-only → skip all; complex → call code review + run code-review high; sensitive (not complex) → call code review + run code-review; non-trivial otherwise → run code-review.
2. If any reviewer — including Codex review — found **any** issues (Critical, Important, minor, or suggestions): `AskUserQuestion` "Found N issues and M suggestions. Fix any before committing, or proceed?"
3. Perform commit loop, below.

## Codex Review (parallel second opinion)

When the preflight steps include a **"run codex review"** directive, run it *concurrently* with the other review steps so its latency overlaps theirs instead of adding to them.
It is a Codex (GPT-5) adversarial second opinion via the OpenAI codex plugin's companion script, invoked directly because the `/codex:review` slash command is `disable-model-invocation` (the model cannot call it).
The determiner emits this directive **only when the codex plugin is installed**, and embeds the exact, already-resolved launch command — `node "<companion>" review --cwd "<repo-root>"` — so there is nothing to resolve here, and a host without codex never sees this step at all. Use the embedded path/command verbatim; do not construct your own.

**Phase A — readiness (before running the other review steps):**

1. Probe auth with the embedded companion path: `node "<companion>" setup --json`, then read `.ready`.
   - `.ready == true` → go to Phase B.
   - `.ready == false` → `AskUserQuestion` surfacing the probe's `.nextSteps` (e.g. "Run `codex login`"), with options "I've authenticated — re-check" and "Skip Codex this commit". On re-check, re-run the probe; if still not ready, skip.
   - the probe errors or the companion has gone missing → skip Codex **silently** and continue. A missing optional reviewer must never block a commit.

**Phase B — launch (returns immediately):**

1. Launch the directive's embedded command in the background — this is what makes it parallel — with `Bash` and `run_in_background: true`, e.g.:

   ```bash
   node "<companion>" review --cwd "<repo-root>"
   ```

2. Record the background task id and do not wait — proceed straight to the other preflight steps.

   Codex reviews the repo's full working-tree diff, which for `/commit` may include out-of-scope (pre-existing, non-session) changes. That is expected — Phase D filters them back to scope.

**Phase C — run the other preflight steps** (feature-dev:code-reviewer, code-review / code-review high) while Codex works underneath.

**Phase D — collect (before the step-2 issues gate):**

1. Read the background task's output file (or use `TaskOutput`). If it has not finished, surface a one-line status such as "*Codex still reviewing…*" and poll again until the task exits.
2. **Failure contract (no silent pass):** if the task exit code is non-zero, or its output lacks a `# Codex Review` block, report "Codex review FAILED — not counted" and treat Codex as having produced no verdict. Do not imply it passed; continue with the other reviewers' findings.
3. **Scope filter (critical for `/commit`):** Codex reviews the whole working tree, but this command's SCOPE may be narrower (session-only). Before merging, discard any Codex finding whose file is outside the in-scope set — never auto-fix, surface, or gate on a finding for an out-of-scope file. For `/commitall` (scope = all uncommitted changes) nothing is filtered.
4. On success, parse the (in-scope) findings from the `# Codex Review` block. Findings are priority-tagged:
   - `[P1]` → treat as Critical: auto-fix.
   - `[P2]` → treat as Important: auto-fix.
   - lower or untagged → surface, do not auto-fix.

   A clean review (exit 0, header present, no `[P#]` findings) is a pass — surface its no-issues note and move on. Show Codex's in-scope findings verbatim alongside the other reviewers', and fold their count into the step-2 gate.

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

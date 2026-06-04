#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["complexipy", "lizard"]
# ///
"""Deterministic preflight determiner for /commit and /commitall.

Decides — without burning model tokens — which (if any) review/code-review
pre-flight steps a changeset warrants, by measuring:

  1. Δloc          — added+deleted lines (whole working tree vs HEAD + untracked)
  2. complexity    — Python: cognitive (complexipy); other code: cyclomatic (lizard).
                     Diff-scoped: only functions the diff actually touched count,
                     so a docstring/comment/version-string edit to a file with a
                     gnarly *untouched* function does not inherit its complexity.
  3. file classes  — code vs docs vs data/config
  4. sensitivity   — path globs (auth/crypto/payments/migrations/CI/hooks/...) +
                     git bug-fix "regression gravity" + code deletions

Risk is the product of *how hard to get right* (complexity/loc) and *how bad
if wrong* (sensitivity/gravity): a one-line auth or migration change escalates
even though it is tiny.

Output is human-legible AND machine-parseable: metrics, a decision label, a
literal ordered list of preflight steps the workflow must execute, and the
rationale. The irreducibly-semantic work (commit grouping + messages) stays
with the model; this script only gates the mechanical review intensity.

Exit code is always 0 — a determiner must never block a commit workflow.
Per-file metric failures degrade to Δloc rather than aborting.
"""
from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field

# ---- tuning thresholds (personal tool; tune freely) ------------------------
TRIVIAL_LOC = 15            # code loc at/below which a non-sensitive change is trivial
TRIVIAL_COG = 5             # max cognitive complexity for "trivial"
TRIVIAL_CCN = 5             # max cyclomatic complexity for "trivial"
COMPLEX_COG = 15            # max cognitive complexity that forces escalation
COMPLEX_CCN = 10            # max cyclomatic complexity that forces escalation
COMPLEX_FILES = 10          # >this many code files → escalate
COMPLEX_LOC = 400           # >this much code loc → escalate
GRAVITY_LOG_DEPTH = 40      # commits of history scanned per file for bug-fix density
GRAVITY_HIGH = 0.40         # bug-fix-commit fraction at/above which a file is "high gravity"
MAX_FILES_ANALYZED = 200    # bound runtime on huge changesets

CODE_EXTS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".go", ".rs",
    ".java", ".kt", ".swift", ".c", ".h", ".cpp", ".cc", ".hpp", ".rb",
    ".php", ".cs", ".scala", ".sh", ".bash", ".zsh", ".lua", ".pl", ".r",
}
DOC_EXTS = {".md", ".mdx", ".rst", ".txt", ".adoc"}
DATA_EXTS = {
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".xml", ".csv",
    ".lock", ".env", ".properties", ".conf",
}
SKIP_DIR_RE = re.compile(
    r"(^|/)(node_modules|dist|build|\.venv|venv|__pycache__|\.git|"
    r"vendor|third_party|\.search-rag|\.lance-rag)(/|$)"
)
GENERATED_RE = re.compile(r"(\.min\.(js|css)$|\.generated\.|_pb2\.py$|\.lock$)")

# Path-sensitivity: a hit on any of these escalates regardless of size.
SENSITIVITY_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("auth/crypto/secret", re.compile(r"(auth|oauth|login|session|token|crypto|"
                                      r"secret|password|credential|jwt|\.pem$|\.key$)", re.I)),
    ("payments/billing", re.compile(r"(payment|billing|invoice|charge|stripe|paypal|checkout)", re.I)),
    ("db migration", re.compile(r"(migrat|/alembic/|schema\.(sql|prisma)$|\.sql$)", re.I)),
    ("CI/CD", re.compile(r"(^|/)(\.github/|\.gitlab-ci|\.circleci/|azure-pipelines|Jenkinsfile)", re.I)),
    ("hooks", re.compile(r"(^|/)hooks?/|hooks\.json$|pre-commit", re.I)),
    ("agent/harness config", re.compile(r"(settings\.(json|local\.json)$|(^|/)\.claude/|CLAUDE\.md$)", re.I)),
    ("dependency lockfile", re.compile(r"(package-lock\.json|yarn\.lock|pnpm-lock|uv\.lock|"
                                       r"poetry\.lock|Cargo\.lock|go\.sum|Gemfile\.lock|requirements\.txt)$", re.I)),
    ("infra/deploy", re.compile(r"(Dockerfile|docker-compose|\.tf$|/k8s/|/helm/|/terraform/)", re.I)),
]
BUGFIX_MSG_RE = re.compile(r"\b(fix|bug|hotfix|revert|regress|patch)\b", re.I)
# Unified-diff hunk header: @@ -old[,n] +new[,m] @@ — we key on the new side.
HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def git(*args: str) -> str:
    """Run a git command, returning stdout (empty string on failure)."""
    try:
        return subprocess.run(
            ["git", *args], capture_output=True, text=True, check=False
        ).stdout
    except Exception:
        return ""


def changed_new_lines(path: str, status: str) -> set[int] | None:
    """Return new-side line numbers the diff touches, or None for whole-file.

    None signals "treat every line as changed" — used for added/untracked
    files (no prior version to diff against) and for any diff we cannot parse,
    so the determiner degrades toward over-review rather than missing a change.

    Args:
        path: Repo-root-relative file path.
        status: Single-letter git status (A added, M modified, ...).

    Returns:
        Set of 1-based new-side line numbers, or None to mean the whole file.
    """
    if status == "A":
        return None
    out = git("diff", "HEAD", "--unified=0", "--no-renames", "--", path)
    if not out.strip():
        return None  # no tracked diff (e.g. untracked) → whole file
    lines: set[int] = set()
    for line in out.splitlines():
        m = HUNK_RE.match(line)
        if not m:
            continue
        start = int(m.group(1))
        length = int(m.group(2)) if m.group(2) is not None else 1
        if length == 0:
            # Pure deletion: no new-side lines exist, but the removal sits
            # between new lines `start` and `start+1` — count both so a
            # deletion inside a function still marks that function touched.
            lines.add(start)
            lines.add(start + 1)
        else:
            lines.update(range(start, start + length))
    return lines


# Languages whose full-line comment token lets us cheaply classify diff lines.
# Python is absent on purpose: its docstrings have no comment marker, so it
# uses the exact AST path below instead of this conservative line heuristic.
LINE_COMMENT_PREFIXES: dict[str, tuple[str, ...]] = {
    ".js": ("//",), ".jsx": ("//",), ".ts": ("//",), ".tsx": ("//",),
    ".mjs": ("//",), ".cjs": ("//",), ".go": ("//",), ".rs": ("//",),
    ".java": ("//",), ".kt": ("//",), ".swift": ("//",), ".c": ("//",),
    ".h": ("//",), ".cpp": ("//",), ".cc": ("//",), ".hpp": ("//",),
    ".cs": ("//",), ".scala": ("//",), ".php": ("//",),  # not "#": PHP 8 #[Attr] is code
    ".sh": ("#",), ".bash": ("#",), ".zsh": ("#",), ".rb": ("#",),
    ".pl": ("#",), ".r": ("#",), ".lua": ("--",),
}
_PY_DOCABLE = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _strip_py_docstrings(tree: ast.AST) -> ast.AST:
    """Drop the leading string-literal statement from every docable scope.

    Mutates the tree in place and returns it. After stripping, two trees that
    differ only in docstrings (or comments, which never enter the AST) dump
    identically.
    """
    for node in ast.walk(tree):
        if isinstance(node, _PY_DOCABLE):
            body = node.body
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                node.body = body[1:]
    return tree


def _py_doc_only(old_src: str, new_src: str) -> bool:
    """Decide whether a Python edit is a semantic no-op.

    Compares the docstring-stripped ASTs of the two revisions. `ast.dump`
    omits line numbers, so comments, docstrings, and pure reformats (whitespace,
    reflows) do not register; only a semantic (executable) difference makes the
    dumps diverge. AST-identity is a strictly safe short-circuit: by definition
    there is no behaviour change for a correctness reviewer to act on.

    Args:
        old_src: File contents at HEAD.
        new_src: Working-tree file contents.

    Returns:
        True when the two revisions are semantically identical — only comments,
        docstrings, or formatting changed. False on any syntax error (degrade
        toward review).
    """
    try:
        a = ast.dump(_strip_py_docstrings(ast.parse(old_src)))
        b = ast.dump(_strip_py_docstrings(ast.parse(new_src)))
    except SyntaxError:
        return False
    return a == b


def _line_doc_only(path: str, prefixes: tuple[str, ...]) -> bool:
    """Decide whether a non-Python edit changed only comments/blank lines.

    Conservative line heuristic: every added/removed diff line must be blank or
    start with a full-line comment token. Anything else — including block
    comments and string-literal prose we cannot prove are non-code — counts as
    code and suppresses the short-circuit, so we under-claim doc-only rather
    than skip review on a real change.

    Args:
        path: Repo-root-relative file path.
        prefixes: Full-line comment tokens for the file's language.

    Returns:
        True when at least one line changed and every changed line is blank or a
        line comment.
    """
    out = git("diff", "HEAD", "--unified=0", "--no-renames", "--", path)
    if not out.strip():
        return False
    saw_change = False
    for line in out.splitlines():
        if not line or line[0] not in "+-" or line.startswith(("+++", "---")):
            continue
        content = line[1:].strip()
        saw_change = True
        if content and not content.startswith(prefixes):
            return False
    return saw_change


@dataclass
class FileChange:
    path: str
    added: int = 0
    deleted: int = 0
    status: str = "M"          # M, A, D, R...
    binary: bool = False
    klass: str = "other"       # code | docs | data | other
    cognitive: int = 0         # python cognitive complexity (max touched fn)
    cyclomatic: int = 0        # non-python cyclomatic complexity (max touched fn)
    sensitivity: list[str] = field(default_factory=list)
    gravity: float = 0.0       # bug-fix-commit fraction in recent history
    # New-side line numbers the diff touched; None = whole file (added/untracked
    # or unparseable diff → treat every line as changed, degrading toward review).
    changed_lines: set[int] | None = None
    doc_only: bool = False     # diff touched only comments/docstrings/blank lines


def classify(path: str) -> str:
    _, ext = os.path.splitext(path)
    ext = ext.lower()
    if ext in CODE_EXTS:
        return "code"
    if ext in DOC_EXTS:
        return "docs"
    if ext in DATA_EXTS:
        return "data"
    return "other"


def collect_changes() -> list[FileChange]:
    """Union of tracked changes (staged+unstaged vs HEAD) and untracked files."""
    changes: dict[str, FileChange] = {}

    # --no-renames: decompose renames into delete+add so --name-status and
    # --numstat emit identical plain paths (arrow notation otherwise orphans
    # the numstat entry, silently zeroing loc on renamed files).
    for line in git("diff", "HEAD", "--name-status", "--no-renames").splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        code = parts[0][0]
        path = parts[-1]
        changes[path] = FileChange(path=path, status=code)

    # Tracked: numstat gives loc deltas ("-" means binary).
    for line in git("diff", "HEAD", "--numstat", "--no-renames").splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        a, d, path = parts[0], parts[1], parts[-1]
        fc = changes.setdefault(path, FileChange(path=path))
        if a == "-" or d == "-":
            fc.binary = True
        else:
            fc.added, fc.deleted = int(a or 0), int(d or 0)

    # Untracked files (status --porcelain "??") count fully as additions.
    for line in git("status", "--porcelain").splitlines():
        if not line.startswith("?? "):
            continue
        path = line[3:].strip().strip('"')
        if path.endswith("/"):  # untracked dir — expand
            for root, _, files in os.walk(path):
                for f in files:
                    p = os.path.join(root, f)
                    changes.setdefault(
                        p, FileChange(path=p, status="A", added=line_count(p)))
        else:
            changes.setdefault(
                path, FileChange(path=path, status="A", added=line_count(path)))

    result = []
    for fc in changes.values():
        if SKIP_DIR_RE.search(fc.path):
            continue
        fc.klass = classify(fc.path)
        # Lockfiles / generated read as data, never "code" complexity targets.
        if GENERATED_RE.search(fc.path) and fc.klass == "code":
            fc.klass = "data"
        result.append(fc)
    return result


def line_count(path: str) -> int:
    try:
        with open(path, "rb") as fh:
            return fh.read().count(b"\n") + 1
    except OSError:
        return 0


def _max_touched(
    per_fn: list[tuple[int, int, int]], changed: set[int] | None
) -> int:
    """Max complexity among functions whose body the diff touched.

    Args:
        per_fn: (complexity, line_start, line_end) per function, post-change.
        changed: New-side line numbers the diff touched, or None for whole-file.

    Returns:
        Highest complexity over touched functions; 0 when the diff touched no
        function (e.g. a module docstring or version constant changed but no
        function body did) — this is what keeps such changes off the complex
        tier despite a gnarly untouched function elsewhere in the file.
    """
    touched = [
        cx for cx, lo, hi in per_fn
        if changed is None or any(lo <= ln <= hi for ln in changed)
    ]
    return max(touched, default=0)


def measure_complexity(changes: list[FileChange]) -> None:
    """Fill cognitive (py) / cyclomatic (other) for code files still on disk.

    Complexity is diff-scoped: we compute each function's complexity on the
    post-change working-tree file (complexity is function-scoped), then keep
    only functions the diff actually touched. A change that edits no function
    body — a docstring rewrite, a version-string bump — scores 0, so file-level
    complexity in untouched functions no longer escalates it. Deleted files
    have no on-disk content → skipped. Each file degrades independently.
    """
    py = [c for c in changes if c.klass == "code" and c.path.endswith(".py")
          and c.status != "D" and os.path.isfile(c.path)]
    other = [c for c in changes if c.klass == "code" and not c.path.endswith(".py")
             and c.status != "D" and os.path.isfile(c.path)]

    for c in py + other:
        c.changed_lines = changed_new_lines(c.path, c.status)

    if py:
        try:
            import complexipy  # type: ignore[import-not-found]  # uv-provided
            for c in py:
                try:
                    with open(c.path, encoding="utf-8", errors="replace") as fh:
                        res = complexipy.code_complexity(fh.read())
                    fns = getattr(res, "functions", []) or []
                    per_fn = [(getattr(f, "complexity", 0),
                               getattr(f, "line_start", 0),
                               getattr(f, "line_end", 0)) for f in fns]
                    # With functions, diff-scope to the ones touched (0 if none).
                    # Function-less module code has no per-function span to
                    # intersect, so fall back to the module total — losing that
                    # would silently zero genuinely complex top-level code.
                    c.cognitive = (_max_touched(per_fn, c.changed_lines) if per_fn
                                   else getattr(res, "complexity", 0))
                except Exception:
                    pass
        except Exception:
            pass  # complexipy unavailable → python files degrade to Δloc

    if other:
        try:
            import lizard  # type: ignore[import-not-found]  # uv-provided
            for c in other:
                try:
                    with open(c.path, encoding="utf-8", errors="replace") as fh:
                        a = lizard.analyze_file.analyze_source_code(c.path, fh.read())
                    per_fn = [(fn.cyclomatic_complexity, fn.start_line, fn.end_line)
                              for fn in a.function_list]
                    c.cyclomatic = _max_touched(per_fn, c.changed_lines)
                except Exception:
                    pass
        except Exception:
            pass  # lizard unavailable → non-python files degrade to Δloc


def measure_sensitivity(changes: list[FileChange]) -> None:
    for c in changes:
        for label, pat in SENSITIVITY_RULES:
            if pat.search(c.path):
                c.sensitivity.append(label)
        # Deleting a code file is inherently higher-risk than editing one.
        if c.status == "D" and c.klass == "code":
            c.sensitivity.append("code deletion")


def measure_gravity(changes: list[FileChange]) -> None:
    """Regression gravity: fraction of recent commits touching the file that
    were bug fixes. High = the file historically attracts bugs → review it."""
    for c in changes:
        if c.status == "A":  # brand-new file has no history
            continue
        log = git("log", f"-{GRAVITY_LOG_DEPTH}", "--pretty=%s", "--", c.path)
        msgs = [m for m in log.splitlines() if m.strip()]
        if not msgs:
            continue
        fixes = sum(1 for m in msgs if BUGFIX_MSG_RE.search(m))
        c.gravity = round(fixes / len(msgs), 2)


def measure_doc_only(changes: list[FileChange]) -> None:
    """Flag modified code files whose diff is a semantic no-op.

    Python uses an exact docstring-stripped AST comparison (so comments,
    docstrings, and reformats all count); other languages use the conservative
    line-comment heuristic (comments and blank lines only). Only status-M files
    on disk are considered — a new file is all-new code, a deletion is not docs.
    """
    for c in changes:
        if c.klass != "code" or c.status != "M" or not os.path.isfile(c.path):
            continue
        if c.path.endswith(".py"):
            old = git("show", f"HEAD:{c.path}")
            if not old:
                continue
            try:
                with open(c.path, encoding="utf-8", errors="replace") as fh:
                    new = fh.read()
            except OSError:
                continue
            c.doc_only = _py_doc_only(old, new)
        else:
            _, ext = os.path.splitext(c.path)
            prefixes = LINE_COMMENT_PREFIXES.get(ext.lower())
            if prefixes:
                c.doc_only = _line_doc_only(c.path, prefixes)


def decide(changes: list[FileChange]) -> tuple[str, list[str], list[str], dict]:
    code = [c for c in changes if c.klass == "code"]
    code_loc = sum(c.added + c.deleted for c in code)
    total_loc = sum(c.added + c.deleted for c in changes)
    max_cog = max([c.cognitive for c in code] or [0])
    max_ccn = max([c.cyclomatic for c in code] or [0])
    sens_hits = sorted({s for c in changes for s in c.sensitivity})
    high_gravity = [(c.path, c.gravity) for c in changes if c.gravity >= GRAVITY_HIGH]

    sensitive = bool(sens_hits) or bool(high_gravity)
    complex_ = (
        max_cog >= COMPLEX_COG or max_ccn >= COMPLEX_CCN
        or len(code) > COMPLEX_FILES or code_loc > COMPLEX_LOC
    )
    docs_data_only = not code
    # Every changed code file is a semantic no-op (comments/docstrings/reformat).
    # Checked before the loc-based trivial test so a large doc-only diff (e.g. a
    # 40-line docstring rewrite) still short-circuits instead of hitting the loc
    # gate.
    code_doc_only = bool(code) and all(c.doc_only for c in code)
    trivial = docs_data_only or (
        code_loc <= TRIVIAL_LOC and max_cog <= TRIVIAL_COG and max_ccn <= TRIVIAL_CCN
    )

    metrics = {
        "files": len(changes), "code_files": len(code),
        "total_loc": total_loc, "code_loc": code_loc,
        "max_cognitive_py": max_cog, "max_cyclomatic_other": max_ccn,
        "sensitivity": sens_hits, "high_gravity": high_gravity,
    }

    rationale: list[str] = []
    steps: list[str] = []

    if docs_data_only and not sensitive:
        label = "trivial"
        rationale.append("No code files changed (docs/data/config only) and no "
                          "sensitive paths touched.")
        steps.append("(none — skip code-review; proceed directly to commit)")
    elif code_doc_only and not sensitive:
        label = "trivial"
        rationale.append("Code files changed, but every diff is a semantic "
                          "no-op — only comments, docstrings, or formatting "
                          "changed (verified via AST for Python, line-comment "
                          "scan otherwise) and no sensitive paths touched.")
        steps.append("(none — skip code-review; proceed directly to commit)")
    elif trivial and not sensitive:
        label = "trivial"
        rationale.append(
            f"Small, low-complexity code change (code_loc={code_loc}≤{TRIVIAL_LOC}, "
            f"cog={max_cog}≤{TRIVIAL_COG}, ccn={max_ccn}≤{TRIVIAL_CCN}) with no "
            f"sensitive paths or high-gravity files.")
        steps.append("(none — skip code-review; proceed directly to commit)")
    else:
        if sensitive and not complex_ and code_loc <= TRIVIAL_LOC:
            label = "sensitive"
            rationale.append(
                "Change is small but touches sensitive paths / high-gravity "
                "files — escalated despite size (blast radius > size).")
        elif complex_:
            label = "complex"
            rationale.append(
                f"High-complexity or large change (cog={max_cog}, ccn={max_ccn}, "
                f"code_files={len(code)}, code_loc={code_loc}).")
        else:
            label = "standard"
            rationale.append(
                f"Non-trivial code change (code_loc={code_loc}, cog={max_cog}, "
                f"ccn={max_ccn}).")

        if sens_hits:
            rationale.append("Sensitivity: " + ", ".join(sens_hits) + ".")
        if high_gravity:
            rationale.append("High-gravity files: "
                             + ", ".join(f"{p}({g})" for p, g in high_gravity) + ".")
        if sensitive or complex_:
            steps.append('Run feature-dev:code-reviewer via the Agent tool '
                         '(subagent_type "feature-dev:code-reviewer") on the in-scope changed files; '
                         'show full findings, auto-fix Critical/Important.')
        if complex_:
            steps.append('Run Skill("code-review", "high") on all in-scope code files; '
                         'auto-fix Critical/Important findings.')
        else:
            steps.append('Run Skill("code-review") on all in-scope code files; '
                         'auto-fix Critical/Important findings.')

    return label, steps, rationale, metrics


def main() -> int:
    if not git("rev-parse", "--is-inside-work-tree").strip():
        print("Preflight determination: not a git repository — skipping.")
        return 0
    # Git emits repo-root-relative paths; the `!` directive runs in the
    # session cwd which is not guaranteed to be the repo root. Anchor there
    # so os.path.isfile / os.walk resolve correctly (else complexity would
    # silently measure nothing).
    toplevel = git("rev-parse", "--show-toplevel").strip()
    if toplevel:
        os.chdir(toplevel)

    changes = collect_changes()
    if not changes:
        print("Preflight determination: no changes detected.")
        return 0
    if len(changes) > MAX_FILES_ANALYZED:
        changes = changes[:MAX_FILES_ANALYZED]

    measure_sensitivity(changes)
    measure_gravity(changes)
    measure_complexity(changes)
    measure_doc_only(changes)
    label, steps, rationale, m = decide(changes)

    print("## Preflight determination (deterministic)\n")
    print(f"- Files: {m['files']}  (code: {m['code_files']})")
    print(f"- Δloc: {m['total_loc']} total, {m['code_loc']} in code files")
    print(f"- Max cognitive complexity (Python): {m['max_cognitive_py']}")
    print(f"- Max cyclomatic complexity (other code): {m['max_cyclomatic_other']}")
    print(f"- Sensitivity hits: {', '.join(m['sensitivity']) or 'none'}")
    print(f"- High-gravity files: "
          f"{', '.join(f'{p}({g})' for p, g in m['high_gravity']) or 'none'}")
    print(f"\n**Decision: {label.upper()}**\n")
    print("Preflight steps to follow:")
    for i, s in enumerate(steps, 1):
        print(f" {i}. {s}")
    print("\nRationale:")
    for r in rationale:
        print(f"- {r}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # determiner must never break the commit flow
        print(f"Preflight determination: error ({exc!r}) — "
              f"fall back to manual model-judged gating.")
        sys.exit(0)

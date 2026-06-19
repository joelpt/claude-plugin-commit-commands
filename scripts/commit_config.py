"""CLI for reading and writing commit-commands plugin configuration.

Config file: ``~/.config/commit-commands/config.json``

Keys:
    enforce_commit_commands_use (bool, default true):
        When true, the PreToolUse hook blocks raw ``git commit`` Bash calls
        and redirects to ``/commit`` or ``/commitall``.  Set to false to
        disable the enforcement gate (e.g. in environments where the
        ``/commit`` skill is unavailable or for temporary overrides).

Usage::

    python3 commit_config.py show
    python3 commit_config.py set enforce-commit-commands-use true
    python3 commit_config.py set enforce-commit-commands-use false
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

CONFIG_PATH = Path.home() / ".config" / "commit-commands" / "config.json"

DEFAULTS: dict[str, bool] = {
    "enforce_commit_commands_use": True,
}

app = typer.Typer(help="commit-commands plugin configuration.")


def _load() -> dict[str, bool]:
    """Load config, merging file values over defaults."""
    cfg = dict(DEFAULTS)
    try:
        on_disk = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cfg.update({k: v for k, v in on_disk.items() if k in DEFAULTS})
    except FileNotFoundError:
        pass
    return cfg


def _save(cfg: dict[str, bool]) -> None:
    """Write config atomically, creating parent dirs as needed."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    tmp.replace(CONFIG_PATH)


@app.command("show")
def cmd_show() -> None:
    """Print the current effective configuration as JSON."""
    cfg = _load()
    typer.echo(json.dumps(cfg, indent=2))


@app.command("set")
def cmd_set(
    key: str = typer.Argument(help="Config key (e.g. enforce-commit-commands-use)"),
    value: str = typer.Argument(help="Value: true or false"),
) -> None:
    """Set a config key.  Key accepts hyphens or underscores interchangeably."""
    normalised = key.replace("-", "_")
    if normalised not in DEFAULTS:
        typer.echo(f"Unknown key: {key!r}. Valid keys: {list(DEFAULTS)}", err=True)
        raise typer.Exit(code=1)
    if value.lower() not in ("true", "false"):
        typer.echo(f"Value must be 'true' or 'false', got: {value!r}", err=True)
        raise typer.Exit(code=1)
    cfg = _load()
    cfg[normalised] = value.lower() == "true"
    _save(cfg)
    typer.echo(json.dumps(cfg, indent=2))


if __name__ == "__main__":
    app()

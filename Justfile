# Default recipe: run the tests.
default: test

# Run the test suite: pytest (credit + hook) plus the standalone determiner script.
test:
    uv run --quiet --with pytest pytest tst/ -q
    uv run --quiet --with typer python tst/test_determiner_codex.py

# Lint the Python sources with ruff.
lint:
    uv run --quiet --with ruff ruff check scripts hooks tst

# Smoke-check: confirm the manifest/hooks parse and every hook/script compiles.
smoke:
    python3 -c "import json; json.load(open('.claude-plugin/plugin.json'))"
    python3 -c "import json; json.load(open('hooks/hooks.json'))"
    python3 -m py_compile hooks/*.py scripts/*.py
    @echo "smoke OK"

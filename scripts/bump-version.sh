#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYPROJECT="$REPO_ROOT/pyproject.toml"
INIT_PY="$REPO_ROOT/src/skillsaw/__init__.py"

current_version=$(sed -n 's/^version = "\(.*\)"/\1/p' "$PYPROJECT")

if [[ -z "$current_version" ]]; then
    echo "Error: could not determine current version from $PYPROJECT" >&2
    exit 1
fi

if [[ $# -eq 1 ]]; then
    new_version="$1"
else
    IFS='.' read -r major minor patch <<< "$current_version"
    new_version="$major.$minor.$((patch + 1))"
fi

echo "Bumping version: $current_version -> $new_version"

# Use python for portable in-place editing (works on both macOS and Linux).
# Values are passed as arguments (not interpolated into source) to avoid
# injection if a version string contains quotes or backslashes.
"$REPO_ROOT/.venv/bin/python3" - "$PYPROJECT" "$INIT_PY" "$current_version" "$new_version" <<'PY'
import sys
from pathlib import Path

pyproject, init_py, current_version, new_version = sys.argv[1:]
targets = [
    (pyproject, f'version = "{current_version}"', f'version = "{new_version}"'),
    (init_py, f'__version__ = "{current_version}"', f'__version__ = "{new_version}"'),
]

# Phase 1: validate all files before writing any
updates = []
for path, old, new in targets:
    text = Path(path).read_text(encoding="utf-8")
    if old not in text:
        print(f"Error: could not find {old!r} in {path}", file=sys.stderr)
        sys.exit(1)
    updates.append((path, text.replace(old, new, 1)))

# Phase 2: write all files
for path, content in updates:
    Path(path).write_text(content, encoding="utf-8")
PY

echo "Updated:"
echo "  $PYPROJECT"
echo "  $INIT_PY"

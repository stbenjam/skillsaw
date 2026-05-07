#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYPROJECT="$REPO_ROOT/pyproject.toml"
INIT_PY="$REPO_ROOT/src/agentlint/__init__.py"

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

# Use python for portable in-place editing (works on both macOS and Linux)
python3 -c "
import re, sys
for path, pattern, repl in [
    ('$PYPROJECT', r'^version = \"$current_version\"', 'version = \"$new_version\"'),
    ('$INIT_PY', r'^__version__ = \"$current_version\"', '__version__ = \"$new_version\"'),
]:
    text = open(path).read()
    text = re.sub(pattern, repl, text, count=1, flags=re.MULTILINE)
    open(path, 'w').write(text)
"

echo "Updated:"
echo "  $PYPROJECT"
echo "  $INIT_PY"

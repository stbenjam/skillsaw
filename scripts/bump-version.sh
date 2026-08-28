#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYPROJECT="$REPO_ROOT/pyproject.toml"
INIT_PY="$REPO_ROOT/src/skillsaw/__init__.py"
ACTION_YML="$REPO_ROOT/action.yml"

# Docs carrying an install pin that must track the released version. Historical
# "Since vX.Y.Z" lines under docs/rules/ are deliberately excluded -- only the
# two pin patterns below are rewritten, never a bare version string.
PINNED_DOCS=(
    "$REPO_ROOT/README.md"
    "$REPO_ROOT/docs/ci.md"
    "$REPO_ROOT/docs/pre-commit.md"
    "$REPO_ROOT/docs/getting-started.md"
    "$REPO_ROOT/docs/plugins.md"
    "$REPO_ROOT/docs/custom-rules.md"
    "$REPO_ROOT/skills/skillsaw-create-plugin/SKILL.md"
    "$REPO_ROOT/skills/skillsaw-create-plugin/references/rule-authoring.md"
    "$REPO_ROOT/examples/plugins/skillsaw-example-plugin/pyproject.toml"
)

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
# Both python programs are quoted heredocs with values passed as argv: an
# inline double-quoted program hands quotes, backticks, and $ to the shell,
# which word-splits or command-substitutes the source before python sees it.
python3 - "$PYPROJECT" "$INIT_PY" "$ACTION_YML" "$current_version" "$new_version" <<'PY'
import re, sys

pyproject, init_py, action_yml, current, new = sys.argv[1:6]
for path, pattern, repl in [
    (pyproject, r'^version = "' + re.escape(current) + '"', 'version = "' + new + '"'),
    (init_py, r'^__version__ = "' + re.escape(current) + '"', '__version__ = "' + new + '"'),
    (action_yml, r"default: '" + re.escape(current) + "'", "default: '" + new + "'"),
]:
    text = open(path).read()
    text = re.sub(pattern, repl, text, count=1, flags=re.MULTILINE)
    open(path, 'w').write(text)
PY

echo "Updated:"
echo "  $PYPROJECT"
echo "  $INIT_PY"
echo "  $ACTION_YML"

# Rewrite install pins in docs. Each file is optional -- docs get reorganized,
# and a missing file or absent pin is not an error.
for doc in "${PINNED_DOCS[@]}"; do
    [[ -f "$doc" ]] || continue
    python3 - "$doc" "$current_version" "$new_version" <<'PY'
import re, sys

path, current, new = sys.argv[1:4]
text = original = open(path).read()
for pattern, repl in [
    (r'skillsaw==' + re.escape(current), 'skillsaw==' + new),
    (r'rev: v' + re.escape(current), 'rev: v' + new),
    # Plugin dependency floors track the release so scaffolded plugins
    # never pin a version that does not exist (see test_release_metadata).
    # Prose like "requires skillsaw X or newer" is deliberately NOT
    # rewritten: it records the release that introduced an API, which
    # does not move.
    (r'skillsaw>=' + re.escape(current), 'skillsaw>=' + new),
    # The action's documented version input default, which
    # test_release_metadata pins to the project version.
    (r'install \| `' + re.escape(current) + r'`', 'install | `' + new + '`'),
]:
    text = re.sub(pattern, repl, text)
if text != original:
    open(path, 'w').write(text)
    print('  ' + path)
PY
done

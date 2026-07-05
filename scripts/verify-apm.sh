#!/usr/bin/env bash
#
# verify-apm.sh — Non-destructively verify that the apm-managed agent-context
# directories exactly match a fresh generation from their sources
# (.apm/, apm.yml, skills/).
#
# apm install/compile only ever *write* managed files; they never delete
# unmanaged ones. So "regenerate in place, then `git status`" (what the CI
# verify-update job does via `make update`) cannot catch a PR that *injects* a
# brand-new file into a managed agent directory — the injected file survives
# regeneration and the tree stays clean. `apm audit` is likewise blind to
# foreign files (it only re-hashes files it already tracks).
#
# This script closes that gap. It regenerates the managed tree into a throwaway
# scratch directory and diffs it against the working tree. It NEVER writes into
# the working tree, so it is safe to run locally without risking uncommitted
# work. It fails on:
#   - injected/unmanaged files in a managed dir (present in tree, not generated)
#   - tampered generated files (content differs from source)
#   - missing files (generated from source but not committed)
#
# Requires: APM_VERSION in the environment (the Makefile passes it), uvx, git.

set -euo pipefail

APM_VERSION="${APM_VERSION:?APM_VERSION must be set — run via 'make verify-apm'}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Directories apm generates into, compared recursively (fully apm-managed).
MANAGED_DIRS=(
  .agents/skills
  .claude/rules
  .claude/skills
  .cursor/rules
  .github/instructions
)
# Individual files apm generates.
MANAGED_FILES=(
  AGENTS.md
  .github/copilot-instructions.md
)
# Agent-directory roots apm may emit into; used by the safety net below.
AGENT_ROOTS=(.agents .claude .codex .cursor .gemini .opencode .github AGENTS.md)

APM=(uvx --from "apm-cli@${APM_VERSION}" apm)

SCRATCH="$(mktemp -d)"
trap 'rm -rf "$SCRATCH"' EXIT

echo "[verify-apm] Regenerating managed files into a scratch dir (non-destructive)..."
cp apm.yml "$SCRATCH"/
cp -a .apm skills "$SCRATCH"/
[ -d .claude-plugin ] && cp -a .claude-plugin "$SCRATCH"/
git init -q "$SCRATCH"
(
  cd "$SCRATCH"
  "${APM[@]}" install --force >/dev/null
  "${APM[@]}" compile >/dev/null
)

status=0

# Safety net: every file apm generates under an agent root must be covered by
# MANAGED_DIRS/MANAGED_FILES. If a future apm version emits a new location, fail
# loudly so this gate gets updated rather than silently leaving that path
# unverified.
covered() {
  local f="$1" d
  for d in "${MANAGED_DIRS[@]}"; do [[ "$f" == "$d/"* ]] && return 0; done
  for d in "${MANAGED_FILES[@]}"; do [[ "$f" == "$d" ]] && return 0; done
  return 1
}
while IFS= read -r f; do
  f="${f#./}"
  if ! covered "$f"; then
    echo "[verify-apm] ERROR: apm generated '$f', which this gate does not check."
    echo "             Add it to MANAGED_DIRS/MANAGED_FILES in scripts/verify-apm.sh."
    status=1
  fi
done < <(cd "$SCRATCH" && find "${AGENT_ROOTS[@]}" -type f 2>/dev/null)

# Compare each managed dir/file: scratch (source of truth) vs working tree.
for d in "${MANAGED_DIRS[@]}"; do
  [ -e "./$d" ] || [ -e "$SCRATCH/$d" ] || continue
  if out="$(diff -rq --no-dereference "$SCRATCH/$d" "./$d" 2>&1)"; then :; else
    status=1
  fi
  [ -n "$out" ] && echo "${out//"$SCRATCH"/(generated)}"
done
for f in "${MANAGED_FILES[@]}"; do
  if ! diff -q "$SCRATCH/$f" "./$f" >/dev/null 2>&1; then
    echo "(generated)/$f and ./$f differ (or are missing)"
    status=1
  fi
done

if [ "$status" -ne 0 ]; then
  cat <<'EOF'

[verify-apm] FAILED: agent directories do not match their apm sources.
  - "Only in ./…"  → an unmanaged/injected file: remove it, or add its source
                     under .apm/ (or apm.yml) and run 'make update'.
  - "Only in (generated)…" → a generated file is missing: run 'make update'.
  - "… differ"     → a generated file was hand-edited: run 'make update'.
EOF
  exit 1
fi

echo "[verify-apm] OK: agent directories exactly match apm sources."

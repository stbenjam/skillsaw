#!/usr/bin/env bash
set -euo pipefail

# Shared implementation for the root and dedicated link-check Actions. Keep
# policy in each action.yml; keep input validation, installation, invocation,
# and report outputs here so the two public entry points cannot drift.
ARGS=()
if [[ "${SKILLSAW_STRICT:-false}" == "true" ]]; then
  ARGS+=(--strict)
fi
if [[ -n "${SKILLSAW_FAIL_ON:-}" ]]; then
  case "$SKILLSAW_FAIL_ON" in
    error|warning|info) ARGS+=(--fail-on "$SKILLSAW_FAIL_ON") ;;
    *) echo "Invalid fail-on value: $SKILLSAW_FAIL_ON (expected error, warning, or info)" >&2; exit 1 ;;
  esac
fi
if [[ -n "${SKILLSAW_RULE:-}" ]]; then
  # Split on newlines and commas, then admit only kebab-case rule ids. Rule
  # selection does not grant capabilities: network access remains a separate
  # input below.
  while IFS= read -r RULE_LINE; do
    RULE_ID="${RULE_LINE#"${RULE_LINE%%[![:space:]]*}"}"
    RULE_ID="${RULE_ID%"${RULE_ID##*[![:space:]]}"}"
    [[ -z "$RULE_ID" ]] && continue
    if ! printf '%s' "$RULE_ID" | LC_ALL=C grep -qE '^[a-z0-9][a-z0-9-]*$'; then
      echo "Invalid rule id: $RULE_ID (expected a kebab-case rule id, e.g. content-weak-language)" >&2
      exit 1
    fi
    ARGS+=(--rule "$RULE_ID")
  done <<< "${SKILLSAW_RULE//,/$'\n'}"
fi
if [[ "${SKILLSAW_VERBOSE:-false}" == "true" ]]; then
  ARGS+=(-v)
fi
if [[ "${SKILLSAW_NO_CUSTOM_RULES:-true}" == "true" ]]; then
  ARGS+=(--no-custom-rules)
fi
# Anything but the literal "false" keeps the network off. This input only
# takes capability away, so a typo resolves toward the restriction.
if [[ "${SKILLSAW_NO_NETWORK_INPUT:-true}" != "false" ]]; then
  ARGS+=(--no-network)
fi

REPORT_DIRECTORY="${SKILLSAW_REPORT_DIRECTORY:-${RUNNER_TEMP:-${TMPDIR:-/tmp}}}"
REPORT_FILE=$(mktemp "${REPORT_DIRECTORY%/}/skillsaw-report.XXXXXX")

ACTION_ROOT="${SKILLSAW_ACTION_ROOT:?SKILLSAW_ACTION_ROOT is required}"
if [[ -f "$ACTION_ROOT/pyproject.toml" ]]; then
  pip install -q "$ACTION_ROOT"
elif [[ -n "${SKILLSAW_VERSION:-}" ]]; then
  pip install -q "skillsaw==$SKILLSAW_VERSION"
else
  echo "Cannot install skillsaw: action source and version are both unavailable" >&2
  exit 1
fi

if [[ -n "${SKILLSAW_PLUGINS:-}" ]]; then
  REQUIREMENTS=$(mktemp "${REPORT_DIRECTORY%/}/skillsaw-plugins.XXXXXX")
  trap 'rm -f "$REQUIREMENTS"' EXIT
  printf '%s\n' "$SKILLSAW_PLUGINS" > "$REQUIREMENTS"
  pip install -q -r "$REQUIREMENTS"
  rm -f "$REQUIREMENTS"
  trap - EXIT
fi

set +e
skillsaw lint "${ARGS[@]}" \
  --format text \
  --output "json:$REPORT_FILE" \
  "${SKILLSAW_PATH:-.}"
EXIT_CODE=$?
set -e

{
  echo "exit-code=$EXIT_CODE"
  echo "report-file=$REPORT_FILE"
} >> "${GITHUB_OUTPUT:?GITHUB_OUTPUT is required}"

COUNTS=$(python3 - "$REPORT_FILE" <<'PY' 2>/dev/null || printf '0 0\n'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as report:
    summary = json.load(report)["summary"]
print(summary["errors"], summary["warnings"])
PY
)
read -r ERRORS WARNINGS <<< "$COUNTS"
{
  echo "errors=${ERRORS:-0}"
  echo "warnings=${WARNINGS:-0}"
} >> "$GITHUB_OUTPUT"

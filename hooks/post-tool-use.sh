#!/usr/bin/env bash
# skillsaw PostToolUse hook.
#
# Claude Code passes the tool-call payload as JSON on stdin. This forwards it
# to `skillsaw hook post-tool-use`, which lints the file that was just edited
# using the repository's own .skillsaw.yaml configuration.
#
# No-op (exit 0) when skillsaw is not installed, so the plugin never breaks
# editing for users who have not installed the linter.
command -v skillsaw >/dev/null 2>&1 || exit 0
exec skillsaw hook post-tool-use

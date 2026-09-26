#!/bin/sh
# Fail the tool call when staged files are not formatted.
exec git diff --cached --name-only --diff-filter=ACM | xargs -r black --check

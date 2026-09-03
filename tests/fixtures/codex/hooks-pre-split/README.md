# release-guard

Codex hooks that record every tool call while a release is in flight, so a
failed release can be replayed from the log.

The `matcher` in `hooks/hooks.json` was written as an empty array. Codex
expects a string there and falls back to matching everything, so the hook
runs on every tool call rather than the ones the author meant.

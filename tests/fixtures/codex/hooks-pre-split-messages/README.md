# release-guard

Codex hooks that record every tool call while a release is in flight, so a
failed release can be replayed from the log.

Two defects, one of each kind a pre-0.20.0 baseline has to cope with. The
project file `.codex/hooks.json` writes `hooks` as an array, and the verdict
for that is worded today exactly as `hooks-json-valid` worded it. The plugin
file `hooks/hooks.json` writes `matcher` as an array, and that verdict was
rewritten when the rule was split by host.

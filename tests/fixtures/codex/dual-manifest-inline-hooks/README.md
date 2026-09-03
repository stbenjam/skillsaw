# session-notes

Session bookkeeping published to a Claude Code marketplace and a Codex
catalog from one directory.

`hooks/hooks.json` is the conventional file both hosts load. The Codex
manifest also writes hooks inline, binding `Interrupt` — an event only
Codex dispatches — to a `prompt` handler Codex parses and never runs.

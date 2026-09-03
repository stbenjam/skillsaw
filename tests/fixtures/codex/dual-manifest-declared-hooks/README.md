# policy-guard

Repository policy hooks published to a Claude Code marketplace and a Codex
catalog from one directory.

`hooks/hooks.json` is the conventional file both hosts load. The Codex
manifest declares a second file, `hooks/codex-only.json`, which binds to
`Interrupt` — an event Codex dispatches and Claude Code does not — so
nothing but Codex ever reads it.

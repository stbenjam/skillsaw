# Payments monorepo

Every service under `services/` is started separately, so each one carries
its own `.codex/` layer. Run `make test` at the root before opening a pull
request; it fans out to the per-service suites.

## Hooks

The root layer and four of the services declare Codex hooks in
`.codex/config.toml`. Codex merges that file with `.codex/hooks.json` when a
directory carries both.

## MCP servers

`services/telemetry` declares an MCP server as well as a hook.

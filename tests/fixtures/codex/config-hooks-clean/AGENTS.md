# Ledger reconciliation service

The nightly reconciliation job and its fixtures live here. Run `make test`
before opening a pull request; it seeds a throwaway Postgres and replays a
day of postings, which is the only place a rounding drift shows up.

## Hooks

This project keeps its Codex hooks in `.codex/config.toml` rather than a
separate `hooks.json`, so the whole project layer is one file. Both hooks
shell out to scripts under `scripts/`, which run before the agent has
installed anything — keep them executable and dependency-free.

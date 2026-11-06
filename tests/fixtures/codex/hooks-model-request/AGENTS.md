# Inference gateway

The gateway proxies model calls for the support assistant and records
latency and token usage per request. Run `make test` before opening a pull
request; the contract suite replays recorded model responses offline.

## Hooks

Codex runs the project hooks in `.codex/hooks.json` around every model
request attempt, and `services/gateway/.codex/config.toml` adds the same
pair for the gateway service. The scripts under `scripts/` only append to a
local log, so they are safe to run before anything is installed.

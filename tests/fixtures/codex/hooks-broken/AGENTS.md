# Payments service

The billing API and its ledger workers live here. Run `make test` before
opening a pull request; it seeds a throwaway Postgres and runs the ledger
reconciliation suite, which is the only place double-entry drift shows up.

## Hooks

Codex reads project hooks from `.codex/hooks.json` and plugin hooks from
`plugins/policy-guard/hooks/hooks.json`. Both shell out to scripts under
`scripts/`, so keep those executable and dependency-free — they run before
the agent has installed anything.

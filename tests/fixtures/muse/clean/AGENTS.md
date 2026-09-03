# Ledger service

Double-entry ledger behind the payments API. Go 1.23, Postgres 16, deployed
to the `payments` namespace.

## Build and test

- `make build` compiles the binary into `bin/ledger`.
- `make test` runs the unit suite; it needs no database.
- `make test-integration` starts Postgres in Docker and runs the migration
  suite against it. Run it before any change under `internal/store/`.

## Conventions

- Money is always `int64` minor units. Never introduce a float in
  `internal/ledger/`.
- Every migration in `migrations/` is forward-only and has a matching
  rollback note in its header comment.
- Handlers in `internal/api/` stay thin; posting rules belong in
  `internal/ledger/`.

## Before you commit

Run `make lint` and `make test`. CI runs the same two targets, so a green
local run is a green pipeline.

# Ledger service

Double-entry ledger behind the payments API. Go 1.23, Postgres 16.

## Build and test

- `make build` compiles the binary into `bin/ledger`.
- `make test` runs the unit suite; it needs no database.
- `make test-integration` starts Postgres in Docker.

## Conventions

- Money is always `int64` minor units.
- Handlers in `internal/api/` stay thin; posting rules belong in
  `internal/ledger/`.

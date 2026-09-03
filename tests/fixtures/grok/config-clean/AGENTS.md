# Harbourmaster

Berth-allocation service for a container terminal. Go 1.23, Postgres 16,
deployed to the `quay` namespace.

## Build and test

- `make build` produces `bin/harbourmaster`.
- `make test` runs the unit suite; it needs no database.
- `make test-berths` starts Postgres in Docker and replays the arrival
  fixture. Run it before any change under `internal/allocator/`.

## Conventions

- Berth identifiers are `(terminal, quay, slot)` in that order, and a slot
  is validated at the API boundary rather than deeper in the stack.
- Every migration in `migrations/` is forward-only and carries a rollback
  note in its header comment.
- HTTP handlers in `internal/api/` stay thin; scheduling maths belongs in
  `internal/allocator/`.

## Before you commit

Run `make lint` and `make test`. CI runs the same two, so a green local run
is a green pipeline.

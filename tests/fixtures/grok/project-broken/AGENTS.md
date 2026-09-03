# Waypoint

Route planner for the delivery fleet. Python 3.12, Redis 7, deployed to the
`logistics` namespace.

## Build and test

- `make install` creates the virtualenv and installs the package.
- `make test` runs the unit suite against a fake Redis.
- `make test-live` needs a real Redis; run it before touching
  `waypoint/cache/`.

## Conventions

- Distances are metres as `int`. Never introduce a float into
  `waypoint/routing/`.
- Every scheduled job carries an idempotency key; a job without one is a
  bug, not a style choice.

## Before you commit

Run `make lint` and `make test`.

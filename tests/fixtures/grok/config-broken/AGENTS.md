# Harbourmaster monorepo

Eleven Go services behind one API gateway. Each package under `packages/`
carries its own `.grok/` layer, because Grok Build reads the layer of the
directory it is started in.

## Build and test

- `make build` builds every package.
- `make test` runs the unit suites; none of them need a database.
- `make test-integration` starts Postgres in Docker. Run it before any
  change that touches a migration.

## Conventions

- A package owns its migrations and never reads another package's tables.
- Configuration lives in the package's own Grok layer, so a change to
  one service does not move another's servers.

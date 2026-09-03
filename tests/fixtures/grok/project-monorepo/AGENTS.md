# Tessellate

Cargo workspace for the tile server. Each crate under `packages/` is
released on its own cadence and carries its own agent configuration.

## Build and test

- `cargo build --release` builds every member of the workspace.
- `cargo test --workspace` runs the unit suites; none of them need a
  database.
- `make test-tiles` starts PostGIS in Docker and replays the fixture
  extract. Run it before any change under `packages/tiler/`.

## Conventions

- Tile coordinates are always `(z, x, y)` in that order, and `z` is
  clamped to 0-22 at the edge rather than deeper in the stack.
- A crate that needs its own rules, skills or hooks puts them in its own
  `.grok/`, not the workspace root's.

## Before you commit

Run `cargo clippy --workspace` and `cargo test --workspace`. CI runs the
same two, so a green local run is a green pipeline.

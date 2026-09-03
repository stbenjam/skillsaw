# Tessellate

Tile-server for vector map data. Rust 1.83, PostGIS 16, deployed to the
`maps` namespace.

## Build and test

- `cargo build --release` produces `target/release/tessellate`.
- `cargo test` runs the unit suite; it needs no database.
- `make test-tiles` starts PostGIS in Docker and replays the fixture
  extract. Run it before any change under `crates/tiler/`.

## Conventions

- Tile coordinates are always `(z, x, y)` in that order, and `z` is
  clamped to 0-22 at the edge rather than deeper in the stack.
- Every migration in `migrations/` is forward-only and carries a rollback
  note in its header comment.
- HTTP handlers in `crates/serve/` stay thin; projection maths belongs in
  `crates/tiler/`.

## Before you commit

Run `cargo clippy` and `cargo test`. CI runs the same two, so a green local
run is a green pipeline.

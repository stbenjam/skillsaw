# Working on the tiler

Tile pyramids are expensive to rebuild, so treat `crates/tiler/` as the
hot path.

- Read `docs/pyramid.md` before changing how a zoom level is derived.
- Benchmarks live in `benches/`. Run `cargo bench --bench pyramid` and
  compare against the checked-in baseline before claiming a speedup.
- Never widen a tile coordinate to `i64`. The wire format is `u32` and a
  cast at the boundary hides the overflow rather than fixing it.

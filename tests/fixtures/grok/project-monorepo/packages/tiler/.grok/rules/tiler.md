# Working on the tiler

Tile pyramids are expensive to rebuild, so treat this crate as the hot
path.

- Benchmarks live in `benches/`. Run `cargo bench --bench pyramid` and
  compare against the checked-in baseline before claiming a speedup.
- Never widen a tile coordinate to `i64`. The wire format is `u32` and a
  cast at the boundary hides the overflow rather than fixing it.

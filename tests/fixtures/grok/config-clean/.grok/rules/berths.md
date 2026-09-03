# Working on the allocator

Berth plans are expensive to recompute, so treat `internal/allocator/` as
the hot path.

- Read `docs/allocation.md` before changing how a window is scored.
- Benchmarks live in `internal/allocator/bench/`. Run `make bench` and
  compare against the checked-in baseline before claiming a speedup.
- Never widen a slot index to `int64`. The wire format is `uint32` and a
  cast at the boundary hides the overflow rather than fixing it.

# Berth allocation

`internal/berth/` runs a first-fit allocator over a fixed quay list. It is
deliberately not an optimiser.

- A quay is never oversubscribed, even by one minute. Turnaround time is
  part of the occupancy window.
- Allocation is deterministic: the same input produces the same
  assignment, so a diff of two runs is a real change and not reordering.
- Changing `conf/berth-policy.yaml` requires regenerating
  `testdata/berth-golden.json` with `make berth-golden`.

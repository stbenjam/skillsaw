---
name: profile-endpoint
description: Latency profiling for a single HTTP endpoint.
---

# Profile Endpoint

Attributes an endpoint's p99 to database time, downstream calls, and
in-process work.

## Capturing a profile

Enable the continuous profiler for the target deployment, drive load with
`loadgen`, and export a 60-second window. The flags are listed in [the
loadgen reference](tools/loadgen.md).

## Reading it

Compare the flame graph against the trace waterfall. Time that appears in
the trace but not the profile is time spent waiting on something else,
usually the database. [The trace guide](docs/tracing.md) covers the
waterfall view, and [the query
catalogue](docs/slow-queries.md) the common offenders.

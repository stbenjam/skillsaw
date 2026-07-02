# Known Failure Patterns

Match error clusters against these patterns before summarizing.

## Connection Failures

- `connection refused` / `connection reset` — downstream service is
  down or restarting. Group by target host.
- `timeout waiting for response` — slow dependency. Group by endpoint.

## Resource Exhaustion

- `OutOfMemoryError` / `cannot allocate` — memory pressure. Report the
  process and the time window.
- `too many open files` — file descriptor leak. Report the earliest
  occurrence.

## Data Errors

- `unexpected token` / `parse error` — malformed input. Include one
  sample line in the summary.

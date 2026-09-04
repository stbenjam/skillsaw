# Ferrymark (staging)

Staging checkout of the ferry timetable service. The Antigravity
configuration under `.agents/` is mid-migration from a hand-written
Claude Code setup and has not been validated since.

## Build and test

- `make build` produces `bin/ferrymark`.
- `make test` runs the unit suite; it needs no database.

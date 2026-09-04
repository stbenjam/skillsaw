# Working on the timetable

A published timetable is immutable. `internal/schedule/` never edits a
sailing in place; it writes a superseding row and leaves the original for
the audit trail.

- Read `docs/gtfs.md` before changing how a service calendar is expanded.
- A sailing that crosses midnight keeps the departure date of its origin
  port, not of its arrival.
- Run `make test-schedule` after touching calendar expansion. The unit
  suite does not cover it.
- Never widen `route_id` past 32 bytes. The GTFS feed and the berth
  allocator both index on it.

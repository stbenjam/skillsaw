# Ferrymark

Timetable and berth-allocation service for a coastal ferry operator. Go
1.24, PostgreSQL 16, deployed to the `harbour` namespace.

## Build and test

- `make build` produces `bin/ferrymark`.
- `make test` runs the unit suite; it needs no database.
- `make test-schedule` loads the fixture GTFS feed into a throwaway
  Postgres and replays a week of sailings. Run it before any change under
  `internal/schedule/`.

## Conventions

- A sailing is identified by `(route_id, departure_utc)` in that order,
  and departure times are stored in UTC and rendered in `Europe/Dublin`.
- Every migration in `migrations/` is forward-only and carries a rollback
  note in its header comment.
- HTTP handlers in `internal/api/` stay thin; allocation maths belongs in
  `internal/berth/`.

## Before you commit

Run `make lint` and `make test`. CI runs the same two, so a green local run
is a green pipeline.

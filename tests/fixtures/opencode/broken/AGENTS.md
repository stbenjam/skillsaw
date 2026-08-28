# reporting

Renders scheduled PDF reports from the warehouse. Everything here is
read-only against the warehouse; if you find yourself writing to it, you are
in the wrong service.

## Getting a report to render locally

1. `npm ci`
2. `npm run warehouse:tunnel` — opens a read replica tunnel on port 5439.
3. `npm run render -- --report weekly-revenue --tenant demo`

The rendered PDF lands in `out/`. Open it; the snapshot suite compares
against `fixtures/snapshots/`, so a visual change you did not intend shows
up as a snapshot diff rather than a failure you can skim past.

## Snapshots

`npm run test:snapshot` compares rendered output byte for byte. Update the
stored snapshots only once you have opened the new PDF and confirmed the
change is the one you meant to make — `npm run test:snapshot -- -u` is easy
to reach for and easy to regret.

## Conventions

Query the warehouse through `reporting/warehouse.ts`. It owns the connection
pool and the read-replica routing, and a second connection opened elsewhere
will exhaust the pool under a scheduled run.

Format with `npm run format`. Reference the issue key in the pull request
title, e.g. `REP-31: paginate exports`.

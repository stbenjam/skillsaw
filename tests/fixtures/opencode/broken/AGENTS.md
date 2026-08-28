# AGENTS.md

Conventions for the `reporting` service.

## Build and test

- Install dependencies with `npm ci`.
- Run the unit suite with `npm test`.
- Run the snapshot suite with `npm run test:snapshot`; update snapshots only
  when the rendered report genuinely changed.

## Code conventions

- Format with `npm run format`. CI rejects unformatted code.
- Query the warehouse through `reporting/warehouse.ts`. Do not open a
  connection anywhere else.

## Pull requests

- One logical change per pull request.
- Reference the issue key in the title, e.g. `REP-31: paginate exports`.

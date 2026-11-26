# Tidewater Inventory

Inventory service for the Tidewater warehouses: a Django API in
`packages/api` and a React dashboard in `packages/web`.

## Commands

- `make test` runs both test suites.
- `make migrate` applies database migrations locally.

## Rules

- Every migration needs a reversible `down` step.
- Never edit generated files under `packages/api/schema/`.

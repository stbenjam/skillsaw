# Reporting pipeline

Nightly aggregation jobs for the finance dashboards. Python 3.12, dbt, and
a small FastAPI service that serves the compiled marts.

## Build and test

- `make test` runs the unit suite against the DuckDB fixtures.
- `make dbt-build` compiles and runs every model locally.

## Conventions

- Every model has a schema test; a model without one fails review.
- Keep SQL in `models/`, Python transforms in `transforms/`.

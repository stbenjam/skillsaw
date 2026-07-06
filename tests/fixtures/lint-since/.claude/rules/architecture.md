The service is split into three layers: HTTP handlers in `api/`,
business logic in `core/`, and persistence in `db/`. Handlers never
touch the database directly — they call into `core/` services.

Database migrations live in `db/migrations/` and run with Alembic.
Name migration files with a numeric prefix: `0042_add_index.py`.

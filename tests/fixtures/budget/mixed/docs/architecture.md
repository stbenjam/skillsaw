# Architecture Overview

The order-processing service is three deployables sharing one codebase:

- **API** (`app/api/`): FastAPI handlers, stateless, horizontally scaled.
- **Workers** (`app/workers/`): RabbitMQ consumers, idempotent, one queue
  per domain event.
- **Scheduler** (`app/scheduler/`): cron-style periodic jobs (reconciliation,
  cleanup) running as a single replica.

All three read configuration from `app/config.py` and share the data models
in `app/models/`. The database is PostgreSQL behind SQLAlchemy; migrations
are Alembic revisions in `migrations/`.

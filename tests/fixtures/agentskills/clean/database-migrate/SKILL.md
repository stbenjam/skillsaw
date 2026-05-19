---
name: database-migrate
description: Generate and apply database migration scripts
compatibility: Requires alembic, knex, or goose
metadata:
  author: data-team
  version: "0.8"
---

# Database Migrate

Generate and apply database migration scripts from schema changes.

## When to Use This Skill

Use when the user modifies database models and needs to create a
migration, or when applying pending migrations to an environment.

## Implementation Steps

### Step 1: Detect Migration Tool

Check the project for migration tooling:
1. `alembic.ini` → Alembic (Python / SQLAlchemy)
2. `knexfile.js` → Knex (Node.js)
3. `dbconfig.yml` → Goose (Go)

### Step 2: Generate Migration

Create a new migration file from the current model diff:
- **Alembic**: `alembic revision --autogenerate -m "$DESCRIPTION"`
- **Knex**: `npx knex migrate:make $DESCRIPTION`
- **Goose**: `goose create $DESCRIPTION sql`

### Step 3: Review the Migration

Display the generated SQL and ask the user to confirm:
- Check for destructive operations (DROP TABLE, DROP COLUMN)
- Verify index additions won't lock large tables
- Confirm data backfill steps are idempotent

### Step 4: Apply

Run the migration against the target database:
- **Alembic**: `alembic upgrade head`
- **Knex**: `npx knex migrate:latest`
- **Goose**: `goose up`

Report the migration version and any errors.

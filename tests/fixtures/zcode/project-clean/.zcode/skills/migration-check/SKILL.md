---
name: migration-check
description: Checks a Django migration for locking and reversibility problems. Use when a diff adds or edits files under migrations/.
---

# Migration check

Run `python manage.py sqlmigrate <app> <number>` and read the SQL. Flag any
`ALTER TABLE ... ADD COLUMN ... DEFAULT` on tables over a million rows, and
any migration without a reverse operation.

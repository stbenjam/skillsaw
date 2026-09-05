---
name: review-migration
description: Use when reviewing database migration plans for rollback coverage and schema compatibility before approval.
---

# Review a migration plan

Read the migration plan and identify the tables it changes. Compare each proposed
schema change with the rollback procedure. Record missing rollback steps and ask
for the expected behavior when an older application instance reads the new schema.

Separate confirmed compatibility problems from questions that need an owner.
Return a short review with the affected table, the relevant plan section, and the
smallest change that makes rollback possible.

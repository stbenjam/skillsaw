---
name: misconfigured-agent
description: Reviews database migrations for unsafe schema changes
memory: global
color: teal
permissionMode: plan
---

# Misconfigured Agent

Review each migration file under `migrations/` and flag statements that
lock tables, drop columns, or rewrite large tables without batching.

---
name: rotate-credentials
description: Rotates the database and message-broker credentials.
---

# Rotate Credentials

Credentials for the primary Postgres cluster and the broker rotate every
90 days. Rotation is two-phase: issue the new secret, then retire the old
one once every consumer has reconnected.

## Phase one — issue

Run `vaultctl issue db/primary` and record the lease id. The full
parameter list lives in [the vault reference](docs/vault-reference.md).

## Phase two — retire

Wait for the connection-drain metric to reach zero, then revoke the old
lease. [The drain dashboard](docs/drain-dashboard.md) shows per-consumer
counts.

A consumer that never drains is handled in [the stuck-consumer
guide](runbooks/stuck-consumer.md).

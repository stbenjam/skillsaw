---
name: archive-service
description: Decommissioning path for a retired service.
---

# Archive Service

Retires a service without leaving dangling DNS, orphaned secrets, or
alerts that page someone about a system nobody runs.

## Order of operations

1. Drain traffic and confirm zero requests for seven days.
2. Delete alerts and dashboards.
3. Revoke secrets and service accounts.
4. Archive the repository, keeping the README as a pointer.

Step three is the one people forget; [the secret
inventory](docs/secret-inventory.md) lists every issuer, and [the DNS
inventory](docs/dns-inventory.md) every record.

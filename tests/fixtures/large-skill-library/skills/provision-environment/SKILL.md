---
name: provision-environment
description: Provisions a short-lived preview environment.
---

# Provision Environment

Stands up a namespace holding the service under test, a Postgres instance
seeded from the anonymised snapshot, and a broker.

## Usage

```
envctl create --ttl 48h --seed anonymised
```

The seed dataset and its refresh cadence are described in [the seed-data
notes](docs/seed-data.md), and the namespace quotas in [the quota
table](docs/quotas.md).

## Cleanup

Environments expire on their TTL. Extending one past a week needs an
exception recorded in [the exceptions log](docs/exceptions.md).

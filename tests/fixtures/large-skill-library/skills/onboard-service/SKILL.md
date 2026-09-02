---
name: onboard-service
description: Onboards a new service onto the platform.
---

# Onboard Service

Registers a service in the catalog, wires its CI, and gives it a default
alert set and dashboard.

## Checklist

- A catalog entry with an owning team and a Slack channel.
- A CI pipeline built from [the pipeline
  template](templates/pipeline.yaml).
- Default alerts and a dashboard.
- An entry in the on-call rota.

The catalog schema is in [the catalog
reference](docs/catalog-schema.md), and the dashboard defaults in [the
dashboard notes](docs/dashboards.md).

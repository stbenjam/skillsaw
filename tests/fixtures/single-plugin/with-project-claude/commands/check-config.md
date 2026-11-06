---
description: Check a service configuration file against its JSON Schema
argument-hint: "<config-file>"
---

## Steps

1. Find the schema for $ARGUMENTS under `schemas/` by service name.
2. Validate the file and list every failing path with the schema rule it breaks.

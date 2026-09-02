---
name: audit-dependencies
description: Dependency audit across the service repositories.
---

# Audit Dependencies

Reports which services pull a vulnerable or unmaintained dependency, and
which of those are reachable from a request path.

## Running the audit

`depaudit scan --org platform` writes one JSON report per repository. The
shape of that report is documented in [the report
schema](docs/depaudit-schema.md).

## Reading the results

Reachability matters more than the raw CVE count. A vulnerable parser that
runs only in a build script is not the same risk as one in the request
path — see [the triage rubric](docs/reachability.md).

File one issue per reachable finding, using [the issue
template](templates/security-issue.md).

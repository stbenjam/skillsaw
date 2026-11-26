---
description: Open an incident, page the on-call engineer, and start the timeline
argument-hint: "<severity> <summary>"
---

## Steps

1. Parse the severity (SEV1–SEV4) and summary from $ARGUMENTS.
2. Page the on-call engineer through the `pager` MCP server.
3. Start the incident timeline with the current UTC time and the summary.

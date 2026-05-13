---
description: Search application logs with structured queries
argument-hint: "<service> [--since 1h] [--level error]"
---

## Name
log-analyzer:search

## Synopsis
```
/log-analyzer:search api-gateway --since 1h --level error
```

## Description
Searches application logs from the specified service using structured
query parameters. Supports filtering by time range, log level, and
free-text patterns.

Results are returned as a formatted table with timestamp, level,
service, and message columns.

## Implementation
1. Parse the service name and query parameters from the arguments
2. Construct a log query for the configured log backend (CloudWatch, Datadog, or local files)
3. Execute the query with a maximum of 500 results
4. Parse and deduplicate log entries
5. Format results as a markdown table sorted by timestamp descending
6. Highlight error and warning entries in the output

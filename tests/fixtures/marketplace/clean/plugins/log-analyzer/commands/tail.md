---
description: Stream live log output from a service
argument-hint: "<service> [--level info]"
---

## Name
log-analyzer:tail

## Synopsis
```
/log-analyzer:tail api-gateway --level info
```

## Description
Streams live log output from the specified service. Filters can be
applied to show only specific log levels or patterns.

## Implementation
1. Identify the log source for the specified service from the config
2. Open a streaming connection to the log backend
3. Apply level and pattern filters to incoming entries
4. Display each matching log line with colored level indicators
5. Continue streaming until the user interrupts

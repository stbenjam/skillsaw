---
description: Collect runtime metrics from the running application
argument-hint: "[interval-seconds]"
---

## Name
metrics-collector:collect

## Synopsis
```text
/metrics-collector:collect 30
```

## Description
Samples runtime metrics (CPU, memory, request latency) from the running
application at the given interval and streams them to the metrics warehouse.

## Implementation
1. Connect to the application's metrics endpoint
2. Sample metrics at the requested interval
3. Batch samples and forward them to the warehouse ingestion API
4. Report a summary of collected samples when interrupted

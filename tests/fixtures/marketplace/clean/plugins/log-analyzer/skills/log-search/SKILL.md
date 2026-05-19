---
name: log-search
description: Deep log analysis with pattern recognition and anomaly detection
---

# Log Search

Perform deep analysis of application logs to identify error patterns,
anomalies, and performance regressions.

## When to Use

Invoke this skill when investigating production issues, analyzing error
spikes, or searching for specific log patterns across services.

## Implementation Steps

### Step 1: Gather Context

Ask the user for the time range, affected service, and any known
symptoms or error messages.

### Step 2: Query Logs

Run structured queries against the log backend:
```bash
aws logs filter-log-events --log-group-name /ecs/$SERVICE \
  --start-time $START_MS --end-time $END_MS \
  --filter-pattern "$PATTERN"
```

### Step 3: Analyze Patterns

Group log entries by:
- Error type and stack trace signature
- Request path and HTTP status code
- Time distribution (burst vs. steady)

### Step 4: Report

Present findings with:
- Top error types by frequency
- Timeline of error rate changes
- Affected endpoints and request volumes
- Suggested next steps for remediation

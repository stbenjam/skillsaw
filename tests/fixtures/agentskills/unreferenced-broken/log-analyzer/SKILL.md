---
name: log-analyzer
description: Parse application logs, surface error clusters, and summarize failure patterns
compatibility: Requires Python 3.9+
metadata:
  author: platform-team
  version: "1.0"
---

# Log Analyzer

Parse application log files, group recurring errors, and produce a
summary of failure patterns.

## When to Use This Skill

Use when the user asks to analyze logs, find recurring errors, or
summarize failures from a log file.

## Implementation Steps

### Step 1: Run the Analyzer

Run the bundled analyzer against the log file:

```bash
python scripts/analyze.py --input app.log --format json
```

### Step 2: Classify Failures

Match each error cluster against the known failure patterns documented
in [the pattern reference](references/patterns.md).

### Step 3: Summarize

Report the top error clusters with counts, first/last occurrence
timestamps, and the matched pattern name.

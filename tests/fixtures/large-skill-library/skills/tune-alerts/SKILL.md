---
name: tune-alerts
description: Alert threshold tuning for noisy services.
---

# Tune Alerts

Reduces pager volume without hiding real failures, by moving thresholds
onto symptoms customers feel.

## Method

1. Pull four weeks of alert history.
2. Classify each page: actionable, duplicate, or noise.
3. Delete the noise. Merge the duplicates. Keep the rest.

The classification rules are in [the alert
taxonomy](docs/alert-taxonomy.md), and the history query in [the query
collection](docs/queries.md).

A service whose pages are more than half noise gets its alerting rewritten
rather than tuned; [the rewrite guide](docs/alert-rewrite.md) covers that.

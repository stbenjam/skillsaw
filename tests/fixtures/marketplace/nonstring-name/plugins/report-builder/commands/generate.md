---
description: Generate an analytics report for a given time range
argument-hint: "[range] [--format html|pdf]"
---

## Name
report-builder:generate

## Synopsis
```text
/report-builder:generate last-7-days --format html
```

## Description
Builds an analytics report from the metrics warehouse for the requested
time range and renders it in the chosen output format.

## Implementation
1. Parse the requested time range and validate it against retention limits
2. Query the metrics warehouse for matching data points
3. Aggregate results into report sections
4. Render the report with the selected format template
5. Write the output to `reports/` and print its path

---
name: quarterly-report
description: Build the quarterly revenue report from an exported ledger CSV, including the segment breakdown and the year-over-year comparison. Use when someone asks for the quarterly numbers or a board-ready revenue summary.
---

# Quarterly Report

Export the ledger for the quarter, then build the report:

```bash
python scripts/build_report.py ledger-2026-q1.csv --out report.md
```

## Checking the output

The script prints the totals it computed before writing the file. Compare
them against the ledger's own footer row; a mismatch means the export was
truncated, and the report is not usable.

Pass `--segments` to add the per-segment breakdown, which the board deck
expects but the monthly review does not.

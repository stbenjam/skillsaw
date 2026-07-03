---
name: unreferenced-reachability
description: Generates styled spreadsheet reports with custom fonts and validates the output against the bundled schema. Use when the user asks for a formatted report file.
---

# Report Generator

Generate a styled report, then recalculate its formulas before returning
it to the user.

## Fonts

Search the `./fonts` directory for a typeface matching the user's request
and embed it in the report. Do not download fonts from the network.

## Recalculating

Formula cells are stored as strings until recalculated. Always run:

```bash
python scripts/main.py report.xlsx
```

The script rewrites the workbook in place and prints a summary of the
cells it updated.

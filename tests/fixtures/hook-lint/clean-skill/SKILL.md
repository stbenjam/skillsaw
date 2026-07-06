---
name: clean-skill
description: Generates a styled report and recalculates its formulas before returning it. Use when the user asks for a formatted report file.
---

# Report Generator

Generate a styled report, then recalculate its formulas before returning
it to the user.

## Recalculating

Formula cells are stored as strings until recalculated. Always recalculate
before handing the file back so the user never sees stale values.

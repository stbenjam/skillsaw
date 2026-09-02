# Run deterministic autofixes

Run `skillsaw fix` to apply safe deterministic fixes, then lint again. Plain
`skillsaw fix` repairs errors and warnings only; for a **Fix now** group at
info severity, add `--rule <rule-id>`, which fixes that rule at any severity.
Tell the user which files changed, summarize the resulting diff, and report how
many violations were fixed and how many remain. Retain those counts for the
final summary, then return to the workflow.

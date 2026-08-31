# Run deterministic autofixes

Run `skillsaw fix` to apply safe deterministic fixes — add `--severity info`
when the lint output reports fixable info-level findings — then lint again. Tell the
user which files changed, summarize the resulting diff, and report how many
violations were fixed and how many remain. Retain those counts for the final
summary, then return to the workflow.

# Run deterministic autofixes

Run `skillsaw fix` naming every rule in the **Fix now** bucket, one
`--rule <rule-id>` per rule, then lint again. Add `--suggest` when a named
rule's fixes are suggested rather than safe; the user reviewed them in
triage. Naming the rules keeps the fix inside the confirmed plan, since a
finding the user chose to baseline or configure is left alone, and repairs a
named rule at any severity, so an info-level group needs nothing more. Tell the user which files changed,
summarize the resulting diff, and report how many violations were fixed and
how many remain. Retain those counts for the final summary, then return to the
workflow.

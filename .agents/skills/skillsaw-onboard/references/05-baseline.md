# Step 5: Baseline accepted violations

Offer a baseline only for violations that remain after autofixing and manual
review. Tell the user:

> There are N remaining violations. I can create
> `.skillsaw-baseline.json` so they are accepted for now and only new
> violations fail. You can fix them over time and rerun `skillsaw baseline`
> to shrink the accepted set.

Run `skillsaw baseline` only if the user agrees. Confirm the file exists and
include it in the final changed-file list. Then return to the router and read
Step 6.

# Triage findings from new rules

Only findings from added rules are in scope; findings from existing rules
were already triaged when skillsaw was adopted. For any group with more than
20 findings or making up over 10% of the scan total, review 3–5 sample
findings to understand the pattern before sorting it.

Sort each added-rule group into one of three buckets:

## 1. Fix now

Best for high-priority issues and quick wins:

- All `error` severity findings by default; an error the user accepts as debt
  may move to Baseline instead
- Findings with `"fixable": true`: safe fixes apply with
  `<new-prefix> fix --rule <rule-id>`, suggested ones with `--suggest` added.
  Naming the rule repairs it at any severity
- Small groups of straightforward corrections

## 2. Baseline

Best for valid findings that are not urgent to fix immediately. Recording
them with `<new-prefix> baseline` absorbs the new findings into the existing
baseline file so CI passes while preventing regressions on future changes.
Only errors and warnings can go here: `<new-prefix> baseline` never records
info findings. It records every current non-info finding, so before any
refresh confirm the only unbaselined findings are the ones the user agreed to
baseline, and report `git diff --stat .skillsaw-baseline.json` in the summary.

A removed rule may leave stale baseline entries behind. Before refreshing,
run `<new-prefix>` and confirm the only unbaselined findings are the added
rules' or ones the user has just agreed to baseline: `<new-prefix> baseline`
records every current non-info finding, so refreshing over an unrelated
regression from an existing rule would accept it silently. If other findings
are present, delete the removed rule's entries from `.skillsaw-baseline.json`
instead of regenerating, or resolve those findings first. An ID the new
version still resolves (`<new-prefix> explain <id>` succeeds) is an alias of a
live rule, not a removed rule; leave its entries. Delete a removed rule's key
from `.skillsaw.yaml` too; the new version reports it as `invalid-config`.

## 3. Configure

Best when a new rule clashes with an intentional project convention. Check
`<new-prefix> explain <rule-id>` for options such as `exclude` or limits first,
then consider lowering to `severity: info`, and use `enabled: false` only as
a last resort for advisory content rules. Always add a brief `#` comment in
`.skillsaw.yaml` explaining the rationale.

> [!NOTE]
> Keep security rules (`security-*`, `content-embedded-secrets`,
> `claude-settings-dangerous`), hook rules (`hooks-*`), MCP rules, and
> structural validity rules (`*-valid`, `claude-*-frontmatter`) enabled. Fix
> or baseline these rather than turning them off.

## Presenting the plan to the user

Share the summary table and confirm the plan:

> The upgrade adds {new rule count} with {total} findings in this repo. Here
> is a proposed plan:
> - **Fix now**: {fix count} issues (errors, autofixable findings, and small
>   manual corrections)
> - **Baseline**: {baseline count} existing items to resolve over time
> - **Configure**: {configure count} project-wide conventions in
>   `.skillsaw.yaml`
>
> Would you like to proceed with this plan, or adjust any of the categories?

The fix-now set drives the next edits, the configure set becomes
`.skillsaw.yaml` settings, and the baseline set is recorded with
`<new-prefix> baseline`. Then return to the router.

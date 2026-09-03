# Report new rules and their findings

Compare the rule-ID lists captured in the versions step. Rule IDs are the
indented names in `list-rules` output:

```console
comm -13 <(sort /tmp/skillsaw-rules-old.txt) <(sort /tmp/skillsaw-rules-new.txt)
```

Rules printed by `comm -23` with the files swapped were removed: findings or
baseline entries naming them are stale, and the triage step handles them.

## When no rule was added

Report that the upgrade adds no new checks and return to the router. The pin
updates and the verification step still apply.

## Explain each added rule

For every added rule ID, run `<new-prefix> explain <rule-id>` and summarize
in one line each: what it checks, its default severity, whether it has an
autofix, and its most useful option. Prefer the explanation's own words over
the violation message when describing the rule.

## Scan the repository with the new version

Run the new version over the repository and keep the machine-readable result:

```console
<new-prefix> lint --format json -v > /tmp/skillsaw-update-scan.json
```

Group the findings by `rule_id`, then present one section per added rule:

- the one-line rule summary from its explanation;
- the finding count and severities in this repository;
- two or three representative findings with file paths and line numbers.

Do not propose fixes yet; the triage step sorts each group into fixing,
baselining, or configuring. Record the per-rule groups and return to
the router.

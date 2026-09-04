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

## Lift the config version gate

The config file's top-level `version:` gates rule activation: a rule whose
`since` is newer than that value is skipped unless the file names it, and a
config with no `version` key is read as `0.6.0` (skillsaw prints a warning
saying so). Left stale, it switches off exactly the rules this upgrade added,
and the scan below would report nothing for them. Find the active config:
`<new-prefix> lint -v` prints `Using config: {config}` for `.skillsaw.yaml`,
`.skillsaw.yml`, `.claudelint.yaml` or `.claudelint.yml`. No such line means
no config file exists and nothing is gated, so skip this section. Otherwise
`{old}` is the `version:` value in `{config}`, or `0.6.0` when the key is
absent.

If `{old}` is below `{latest}`, keep a scan taken under the old gate:

```console
<new-prefix> lint --format json -v > /tmp/skillsaw-update-scan-gated.json
```

Then ask:

> {config} reads as version {old}, which keeps every rule added since then
> switched off. Set it to {latest} so those rules run here?

If yes, set (or add) `version: "{latest}"` in `{config}`, keeping its quoting,
and count the file as edited; never create a second config file. The bump
switches on every rule added between `{old}` and `{installed}` as well, not
only the ones the list comparison found, so after the scan below treat each
rule that reports findings there and not in the gated scan as added, for the
report and for triage. If no, the gated rules stay off: run the scan below
anyway and report which added rules it could not exercise.

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

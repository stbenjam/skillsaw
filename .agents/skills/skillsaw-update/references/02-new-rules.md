# Report new rules and their findings

Compare the rule-ID lists captured in the versions step. Rule IDs are the
two-space-indented names in `list-rules` output; the `grep` extracts the ID
alone, leaving the description lines and a `(DEPRECATED …)` annotation
behind, so a deprecated rule does not read as removed:

```console
comm -13 <(grep -oE '^  [a-z][a-z0-9-]*' /tmp/skillsaw-rules-old.txt | sort) <(grep -oE '^  [a-z][a-z0-9-]*' /tmp/skillsaw-rules-new.txt | sort)
```

Rules printed by `comm -23` with the files swapped were removed: findings or
baseline entries naming them are stale, and the triage step handles them.

## Find the active config

The config file's top-level `version:` gates rule activation: a rule whose
`since` is newer than that value is skipped unless the file names it, and a
config with no `version` key is read as `0.6.0` (skillsaw prints a warning
saying so). Left stale, it switches off the rules added since then, and the
scan below would report nothing for them. Find the active config:
`<new-prefix> lint -v` prints `Using config: {config}` for `.skillsaw.yaml`,
`.skillsaw.yml`, `.claudelint.yaml` or `.claudelint.yml`. A non-zero exit
with `Error loading config:` on stderr means the active config could not be
loaded: stop and report that error. No such line on a run that succeeds
means no config file exists and nothing is gated, so skip this section.
Under a container prefix the printed path is the container's: strip
`/workspace/` to reach the host file. A path above the repository is a
parent config skillsaw inherits (`find_config` walks up): never edit it;
read `{config-version}` from it, and when its gate is below `{latest}` ask
whether to lift it there, or run the scans through a temporary copy that
carries `version: "{latest}"`, passed with `-c`, so the comparison still
sees the new rules. Otherwise `{config-version}` is the `version:` value in
`{config}`, or `0.6.0` when the key is absent.

## Lift the config version gate

Do this before deciding whether anything is new: the list comparison above
sees only the binaries, while a gate below `{installed}` keeps rules off that
both binaries carry. If `{config-version}` is below `{latest}`, keep a scan
taken under the old gate:

```console
<new-prefix> lint --format json -v > /tmp/skillsaw-update-scan-gated.json
```

Then ask:

> {config} reads as version {config-version}, which keeps every rule added
> since then switched off. Set it to {latest} so those rules run here?

If yes, set (or add) `version: "{latest}"` in `{config}`, keeping its quoting,
and count the file as edited; never create a second config file. The bump
switches on every rule added between `{config-version}` and `{installed}` as
well, not only the ones the list comparison found: after the scan below, the
rules in its `stats.rules_run` list that the gated scan's list lacks are added
rules too, so run `explain` on each and carry them into the report and the
triage. If no, the gated rules stay off: run the scan below anyway, and
report the rules it could not exercise, which are the `list-rules` IDs absent
from its `stats.rules_run`.

## When no rule was added

If the list comparison adds nothing and the gate needed no change, report
that the upgrade adds no new checks and return to the router; the pin updates
and the verification step still apply.
If the gate was moved, continue below even with an empty comparison: the
rules added between `{config-version}` and `{installed}` are the new checks.

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

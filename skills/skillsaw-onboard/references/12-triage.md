# Triage findings by rule

Run `skillsaw lint --format json -v` so info findings are included. Group
`violations` by `rule_id` and sort the groups by size. For every cluster over
10 percent of the findings or over 20 findings, read three to five of its real
findings before deciding: a count says how loud a rule is, never whether it is
right. Then put each cluster in one of three buckets.

## Fix now

Every `error`, and every finding with `"fixable": true` — `"safe"` fixes come
from `skillsaw fix`, `"suggest"` fixes from `skillsaw fix --suggest` after a
diff review. Small clusters whose samples are cheap, genuine corrections.

## Baseline

Real but not urgent: broken links, over-budget files, long sections, missing
evals. `skillsaw baseline` records them as accepted debt, so CI fails only on
new findings.

## Configure

Structural for this repository: a naming or layout convention, a generated
data directory, a terminology pair used on purpose, an advisory rule the
maintainers will not act on. Configuration states the convention once; a
baseline would re-record it for every file added later.

Take the first rung that works:

1. The rule's own options. `skillsaw explain <rule-id>` prints them —
   `agentskill-unreferenced-files: exclude`, `context-budget: limits`,
   `content-embedded-secrets: additional-placeholders`,
   `content-inconsistent-terminology: groups`. They narrow the rule to this
   repository and keep its other findings.
2. `severity: info`, which keeps the signal without failing CI.
3. `enabled: false`, only for an advisory content rule with no useful option.

Every entry carries a one-line `#` comment giving the reason.

Never configure away hook rules (`hooks-*`), security rules (`security-*`,
`content-embedded-secrets`, `claude-settings-dangerous`), MCP rules (`mcp-*`,
`agent-plugin-mcp-valid`), or format validity rules (`*-valid`,
`*-json-valid`, `claude-agent-frontmatter`, `claude-command-frontmatter`).
A security finding that looks wrong is corrected in the file, not switched
off.

## Worked example

A marketplace of 1,018 skills; first scan 1,957 findings, grade F.

| Rule | Count | Bucket | Proposed action |
| --- | --- | --- | --- |
| `agentskill-unreferenced-files` | 1,018 | Configure | `exclude: ["_scores.json"]` |
| `content-description-routing` | 299 | Baseline | Fix the skills the user names, baseline the rest |
| `agentskill-valid` | 159 | Fix now | Fill or remove the empty `compatibility` key |
| `content-embedded-secrets` | 1 | Fix now | Replace the sample token with `${JWT}` |

The samples decided the buckets. Every unreferenced file is `_scores.json`,
generated ranking data no `SKILL.md` links — a convention, so the rule's
exclusion, which leaves two genuine unreferenced files reported. The routing
findings are correct bare-topic descriptions — 299 rewrites, so fix the
important ones and baseline the rest. The 159 errors are one empty field —
format validity never moves to configure. The lone secret is a sample JWT in
a prompt; `${JWT}` reads as a placeholder and clears it, where disabling the
rule would also hide the real token someone pastes next month.

```yaml
rules:
  # Every skill ships a generated _scores.json for the catalog ranker; it is
  # data, not instructions, so no SKILL.md references it.
  agentskill-unreferenced-files:
    exclude:
      - "_scores.json"
```

## Present the table

Show the clusters before changing anything, then ask:

> {total} findings group into {cluster count} rules. I read samples from the
> {sampled count} largest and propose the table above: fix {fix count} now,
> baseline {baseline count}, configure {configure count} through rule options
> with a reason comment in `.skillsaw.yaml`. Security, hook, MCP, and
> format-validity findings stay in fix or baseline. Proceed, or move a
> cluster first?

The fix-now set drives the next steps, the configure set becomes
`.skillsaw.yaml` edits, and the baseline set is the debt the baseline step
records. Then return to the workflow.

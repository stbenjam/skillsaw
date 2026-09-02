# Triage findings by rule

When onboarding an existing repository, a first scan may surface many findings. Running `skillsaw lint --format json -v` gives you the complete picture, including info-level guidance. Group the findings by `rule_id` and sort them by volume. For any group with more than 20 findings or making up over 10% of the total, review 3–5 sample findings to understand the pattern.

Sort each cluster into one of three practical buckets:

## 1. Fix now
Best for high-priority issues and quick wins:
- All `error` severity findings by default; an error the user accepts as debt, and that the baseline can record, may move to Baseline
- Findings with `"fixable": true`: safe fixes apply with `skillsaw fix`, suggested ones with `skillsaw fix --suggest`. Plain `skillsaw fix` repairs errors and warnings only, so an info-level group needs `skillsaw fix --rule <rule-id>`
- Small groups of straightforward corrections

## 2. Baseline
Best for valid findings that aren't urgent to fix immediately (such as wordy sections, missing evals, or legacy links). Recording them with `skillsaw baseline` lets CI pass immediately while preventing new regressions on future PRs.

Only errors and warnings can go here: `skillsaw baseline` never records info findings. An info cluster the project wants gone belongs in Configure; one it can live with needs no action, since info findings fail CI only under `fail-on: info`.

## 3. Configure
Best for intentional project conventions (such as generated data folders, custom directory layouts, or deliberate terminology choices). Configuring the rule in `.skillsaw.yaml` documents the convention once for all future files:
1. **Rule options**: Check `skillsaw explain <rule-id>` for options like `exclude`, `limits`, or custom `groups`.
2. **Severity**: Lower to `severity: info` to keep helpful feedback without failing CI builds.
3. **Disable**: Use `enabled: false` only as a last resort for advisory content rules without relevant options.

Always add a brief `#` comment in `.skillsaw.yaml` explaining the rationale.

> [!NOTE]
> Keep security rules (`security-*`, `content-embedded-secrets`, `claude-settings-dangerous`), hook rules (`hooks-*`), MCP rules, and structural validity rules (`*-valid`, `claude-*-frontmatter`) enabled. Fix or baseline these rather than turning them off.

## Example walkthrough

Imagine a marketplace with 1,018 skills and an initial scan showing 1,957 findings:

| Rule | Count | Bucket | Action |
| --- | --- | --- | --- |
| `agentskill-unreferenced-files` | 1,018 | Configure | Exclude ranking data: `exclude: ["_scores.json"]` |
| `content-description-routing` | 299 | Baseline | Polish key skills now; baseline the rest for later |
| `agentskill-valid` | 159 | Fix now | Add missing required fields |
| `content-embedded-secrets` | 1 | Fix now | Replace sample API key with `${API_KEY}` placeholder |

In `.skillsaw.yaml`:
```yaml
rules:
  # Skill catalog ranking data is generated automatically and not referenced in SKILL.md
  agentskill-unreferenced-files:
    exclude:
      - "_scores.json"
```

## Presenting the plan to the user

Share the summary table and confirm the plan with the user:

> We found {total} findings across {cluster count} rules. Here is a proposed plan:
> - **Fix now**: {fix count} issues (errors and safe autofixes)
> - **Baseline**: {baseline count} existing items to resolve over time
> - **Configure**: {configure count} project-wide conventions in `.skillsaw.yaml`
>
> Would you like to proceed with this plan, or adjust any of the categories?

The fix-now set drives the next steps, the configure set becomes `.skillsaw.yaml` settings, and the baseline set is recorded in the baseline step.

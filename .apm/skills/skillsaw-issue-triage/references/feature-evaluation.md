# Feature Evaluation — Checklist

A feature request asks skillsaw to do something new — a new rule, flag, config
option, output format, or support for a new tool/format. Your job is to judge
whether it is already possible, in scope, and safe, then enrich it.

## Does it already exist?

- Search existing rules and flags before assuming it is missing:
  `.venv/bin/skillsaw list-rules` (or the rules docs at `skillsaw.org/rules/`)
  and `skillsaw --help`. Check config options in the example config.
- If the ask is already satisfied, redirect the reporter to the existing
  rule/flag/option instead of proposing new work.

## Is it in scope?

- **Core vs. plugin.** skillsaw core targets widely-adopted agentic building
  blocks and formats. Support for a niche or single-vendor tool belongs in a
  **rule plugin**, not core. If the request targets a low-adoption tool, point
  the reporter to the plugin path: <https://skillsaw.org/plugins/>, the
  `skillsaw-create-plugin` skill, and `examples/plugins/skillsaw-example-plugin/`.
- **Configurability.** New rules with tunable behavior must be configurable, and
  new rules default to `enabled: auto` or `enabled: false` — never force-enable
  something that would break existing users.
- **Fit.** Does it match skillsaw's job (linting agent context) rather than
  reformatting, generating, or running agent content?

## Is it safe for existing users?

- Would it change output for existing configs (new violations on files that pass
  today)? That is a backward-compatibility concern and must be opt-in.
- Does it touch stable surfaces — rule IDs, config format, the `claudelint`
  shim, `.claudelint.yaml` discovery? Those must not break.

## Enrichment to add

- Whether the capability already exists (with the rule/flag name if so).
- A core-vs-plugin recommendation with rationale.
- Rough shape of the work: which rule type / node (`context.lint_tree.find(...)`),
  config schema, and `repo_types` it would need.
- Whether it needs integration test coverage with a fixture, and README/docs.
- Related issues or PRs proposing the same thing.

# Feature Evaluation — Checklist

A feature request asks skillsaw to do something new — a new rule, flag, config
option, output format, or support for a new tool/format. Decide the
recommendation: **IMPLEMENT** (build into core), **PLUGIN** (belongs in a rule
plugin), or **REJECT** (out of scope, or already possible).

## 1. Domain gate — is this even skillsaw's job?

skillsaw lints **agentic contextual building blocks**: the prose and structured
config that feed an LLM's context window — `CLAUDE.md`, `AGENTS.md`, `SKILL.md`,
Claude Code plugin/marketplace manifests, agentskills.io, Cursor/Copilot/Gemini
config, CodeRabbit, Promptfoo, APM.

If the request is about anything else — linting a **programming language** or
general source code, or formatting / generating / running content, or an
unrelated tool — it is **out of skillsaw's domain → REJECT**. Recommend closing
as out-of-scope and point to the appropriate dedicated tool. It is **not** a
rule-plugin candidate either: a plugin still runs inside a `RepositoryContext`
over the agent-context file tree, so it cannot lint COBOL, Python, Terraform,
etc. Only continue if the request really is about linting agent context.

## 2. Already possible?

- Search before assuming it's missing: `.venv/bin/skillsaw list-rules` (or
  `skillsaw.org/rules/`), `.venv/bin/skillsaw --help`, and the example config for
  config options.
- If already satisfied → **REJECT** with a redirect to the existing
  rule/flag/option (basis: already supported).

## 3. Core or plugin?

- **In domain and broadly useful** — a widely-adopted agent format, or a check
  valuable to most users → **IMPLEMENT** in core.
- **In domain but niche / single-vendor / low-adoption** → **PLUGIN**: point the
  reporter to <https://skillsaw.org/plugins/>, the `skillsaw-create-plugin`
  skill, and `examples/plugins/skillsaw-example-plugin/`.

## 4. Is it safe for existing users?

- Would it change output for existing configs (new violations on files that pass
  today)? That must be opt-in — new rules default to `enabled: auto` or
  `enabled: false`, never force-enabled.
- Does it touch stable surfaces — rule IDs, config format, the `claudelint` shim,
  `.claudelint.yaml` discovery? Those must not break. A change that would break
  existing users is not **IMPLEMENT** as proposed.

## Enrichment to add

- The recommendation (**IMPLEMENT / PLUGIN / REJECT**) and its one-line basis.
- Whether the capability already exists (with the rule/flag name if so).
- For **IMPLEMENT**: rough shape — which rule type / node
  (`context.lint_tree.find(...)`), config schema, and `repo_types` it needs, plus
  the fixture and README/docs it would require.
- Related issues or PRs proposing the same thing.

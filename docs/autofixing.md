# Autofixing

skillsaw applies deterministic fixes for structural issues. Content-quality violations that need judgment are fixed by coding agents (Claude Code, Cursor, etc.) — the lint interface is familiar, and every violation points to `skillsaw explain` which includes how-to-fix guidance. Rules declare whether they support deterministic autofix (see the **Autofix** column in the [rules reference](rules/index.md)).

## Deterministic Fixes

Safe, pattern-based fixes that run instantly without any external dependencies:

```bash
skillsaw fix                     # Fix errors and warnings (SAFE)
skillsaw fix --dry-run           # Preview safe fixes as colored diffs without writing
skillsaw fix --suggest           # Fix errors and warnings (SAFE + SUGGEST)
skillsaw fix --suggest --dry-run # Preview safe + suggested fixes
skillsaw fix --severity info     # Also apply info-level fixes
```

!!! note "Changed in 0.21"
    Earlier releases applied info-level fixes in every `skillsaw fix` run.
    They are opt-in now — pass `--severity info` or set `fail-on: info`.

By default, `skillsaw fix` repairs errors and warnings. Info-level fixes need
an explicit opt-in: pass `--severity info` (alias: `--fail-on`) or set
`fail-on: info` in `.skillsaw.yaml`. The CLI flag selects an exact scope for
one run; the config setting only ever expands the default scope to info, never
narrows it. Severity and confidence are independent — add `--suggest` to
include SUGGEST fixes within the selected scope.

Examples: adding missing frontmatter, renaming files to kebab-case, registering unregistered plugins in marketplace.json, fixing skill names to match directory names. These are marked **SAFE** confidence and applied automatically.

Some fixes produce cascading changes — for example, renaming a skill name creates stale references in other files. These secondary fixes are marked **SUGGEST** confidence because simple name matching may replace occurrences that aren't actually skill name references. Use `--suggest --dry-run` to review these changes before applying them.

## Fixable Markers in Lint Output

`skillsaw lint` marks each autofixable violation so you know when a fix run is worthwhile, and the summary counts them by confidence:

```
Errors:
  ✗ ERROR (agentskill-valid) [*] [skills/deploy/SKILL.md]: Missing required 'name' field

Warnings:
  ⚠ WARNING (content-broken-internal-reference) [?] [SKILL.md:8]: Broken internal link: [guide](docs/guid.md) — target does not exist (did you mean 'docs/guide.md'?)

Summary:
  Errors:   1
  Warnings: 1
  [*] 1 violation(s) fixable with `skillsaw fix` ([?] 1 more with `skillsaw fix --suggest`)
```

- `[*]` — a **SAFE** fix exists; `skillsaw fix` resolves it (info-level
  findings take `--severity info`).
- `[?]` — a **SUGGEST** fix exists; it is only applied with `skillsaw fix --suggest`.

Info-level findings sit outside the default fix scope, so when they are shown
(with `-v`, or with an info failure threshold) they get their own summary line
advertising `skillsaw fix --severity info`.

Autofix never rewrites vendor-managed plugins under `.codex/plugins/`, even
when a rule reports a finding there. It likewise never rewrites externally
sourced lint-tree content, including APM packages under `apm_modules/` and
skills installed from external `skills-lock.json` sources; those findings
remain diagnostic even when `lint-external-content` is left at its default
`true`.

The JSON format carries the same information as an additive `fixable` boolean (plus `fix_confidence`: `safe` or `suggest` when fixable) on each violation. Fixability is per violation, not per rule — a rule that can only fix some shapes of a problem (e.g. `content-unlinked-internal-reference` only wraps references whose target file exists) marks only those violations. Because `skillsaw fix` batches several violations into one fix per file, its `Fixed N issue(s)` count can differ from the number of marked violations.

!!! note "Removed in 0.15"
    The deprecated `skillsaw lint --fix` flag was removed. `skillsaw fix` is the single entry point for autofixes.

## Working with Coding Agents

If you're already working in a coding agent (Claude Code, Cursor, etc.), you don't need any extra setup — the agent can read skillsaw's lint output and fix violations directly. skillsaw is a standard linter, so agents treat it the same way they treat ESLint or ruff: run it, read the output, fix what it flags. Every violation points to `skillsaw explain <rule-id>`, which provides detailed how-to-fix guidance that agents invoke automatically.

The [onboarding skill](getting-started.md#onboard-with-ai) uses this approach end-to-end — it lints, applies deterministic fixes, then has your agent resolve the remaining violations interactively.

## The skillsaw-fix Skill

For an agent workflow focused purely on fixing, install the [`skillsaw-fix` skill](https://github.com/stbenjam/skillsaw/blob/main/skills/skillsaw-fix/SKILL.md). It gives an agent a repeatable procedure:

1. Run `skillsaw fix` (adding `--severity info` when info-level findings are
   in scope) to apply deterministic fixes first
2. Re-lint and group the remaining violations by rule
3. Run `skillsaw explain <rule-id>` for each rule to load its how-to-fix guidance
4. Make targeted edits, scoped to each violation
5. Re-lint after each file to verify the fix took and nothing regressed

To use it with Claude Code, copy the skill directory into your repo (e.g. `.claude/skills/skillsaw-fix/`) or reference it from a marketplace, then ask the agent to "fix the skillsaw violations".

## The skillsaw-lint Skill

Where `skillsaw-fix` is reactive (violations were reported, fix them), the [`skillsaw-lint` skill](https://github.com/stbenjam/skillsaw/blob/main/skills/skillsaw-lint/SKILL.md) is the proactive guardrail: whenever an agent authors or modifies agentic context — a skill, slash command, agent, hook, plugin, or an instruction file like CLAUDE.md — it lints what it just wrote, applies autofixes, resolves the remaining violations with `skillsaw explain` guidance, and re-lints until clean before reporting the work done.

!!! note "Breaking changes (0.15)"
    Earlier releases shipped a built-in LLM fix path (`skillsaw fix --llm`, the `llm` config section, and the `skillsaw[llm]` extras) powered by LiteLLM. It was removed in 0.15 — coding agents already handle non-deterministic fixes better, with review built into the workflow. An existing `llm:` section in `.skillsaw.yaml` is now ignored with a warning. The long-deprecated `skillsaw lint --fix` flag was removed in the same release.

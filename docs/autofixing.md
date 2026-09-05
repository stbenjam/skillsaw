# Autofixing

skillsaw applies deterministic fixes for structural issues. Content-quality violations that need judgment are fixed by coding agents (Claude Code, Cursor, etc.) — the lint interface is familiar, and every violation points to `skillsaw explain` which includes how-to-fix guidance. Rules declare whether they support deterministic autofix (see the **Autofix** column in the [rules reference](rules/index.md)).

## Deterministic Fixes

Safe, pattern-based fixes that run instantly without any external dependencies:

```bash
skillsaw fix                     # Apply safe structural fixes
skillsaw fix --suggest           # Also apply suggested fixes (e.g. stale references)
skillsaw fix --dry-run           # Preview safe fixes as colored diffs without writing
skillsaw fix --suggest --dry-run # Preview safe + suggested fixes
```

`skillsaw fix` repairs the problems `skillsaw lint` shows. Info-level
findings sit below that bar; `fail-on: info` brings them in, and `--rule`
fixes the named rules at any severity.

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

- `[*]` — the rule declares a **SAFE** fix, eligible for `skillsaw fix`.
- `[?]` — the rule declares a **SUGGEST** fix, requiring `skillsaw fix --suggest`.

Autofix never rewrites vendor-managed plugins under `.codex/plugins/`, even
when a rule reports a finding there. It likewise never rewrites externally
sourced lint-tree content, including APM packages under `apm_modules/` and
skills installed from external `skills-lock.json` sources; those findings
remain diagnostic even when `lint-external-content` is left at its default
`true`.

Symbolic-link files are also diagnostic-only for autofix. Lint does not mark
these findings as fixable. When a selected fix would change a symbolic link,
`skillsaw fix` and `--dry-run` list the skipped path and explain why. For a
content edit, edit the target file directly. For a rename, manually remove,
replace, or rename the symbolic link. Skips for discovered findings are reported
once per path and reason, within the selected severity and confidence, and do
not prevent independent regular-file fixes. A policy-only skip exits successfully; a failed write
still exits nonzero. Dry-run does not apply proposed fixes or run fix callbacks. Existing rename
bookkeeping can still prune stale entries while checking; dry-run is not yet
a fully read-only operation.

Explicit file and directory symlinks passed to `skillsaw fix` are skipped
before CLI path resolution, including dangling links. Name the real file or
directory directly to select it. Other explicitly selected roots still run;
this leaf check does not redefine paths through ancestor directory aliases.

A fix can also update supporting metadata. If that follow-up write fails after
the primary edit, the command reports partial completion and exits nonzero;
the already applied edit is retained.

The JSON format carries an additive `fixable` boolean, plus `fix_confidence`
(`safe` or `suggest`) when fixable. These fields describe declared deterministic
fix support after known path policies: vendor-managed, external, diagnostic-only
and symbolic-link findings have their fixability and confidence cleared. They
do not guarantee application; proposal generation and final filesystem checks
can still skip a fix, including a rename involving another symbolic-link path.
Metadata also covers findings hidden by the default severity threshold, so a
consumer deciding what a plain fix run repairs should check `severity`.

Fixability is per violation, not per rule: for example,
`content-unlinked-internal-reference` marks only references whose target exists.
Because `skillsaw fix` batches several violations into one fix per file, its
`Fixed N issue(s)` count can differ from the number of marked violations.

!!! note "Removed in 0.15"
    The deprecated `skillsaw lint --fix` flag was removed. `skillsaw fix` is the single entry point for autofixes.

## Working with Coding Agents

If you're already working in a coding agent (Claude Code, Cursor, etc.), you don't need any extra setup — the agent can read skillsaw's lint output and fix violations directly. skillsaw is a standard linter, so agents treat it the same way they treat ESLint or ruff: run it, read the output, fix what it flags. Every violation points to `skillsaw explain <rule-id>`, which provides detailed how-to-fix guidance that agents invoke automatically.

The [onboarding skill](getting-started.md#onboard-with-ai) uses this approach end-to-end — it lints, applies deterministic fixes, then has your agent resolve the remaining violations interactively.

## The skillsaw-fix Skill

For an agent workflow focused purely on fixing, install the [`skillsaw-fix` skill](https://github.com/stbenjam/skillsaw/blob/main/skills/skillsaw-fix/SKILL.md). It gives an agent a repeatable procedure:

1. Run `skillsaw fix` to apply all deterministic fixes first
2. Re-lint and group the remaining violations by rule
3. Run `skillsaw explain <rule-id>` for each rule to load its how-to-fix guidance
4. Make targeted edits, scoped to each violation
5. Re-lint after each file to verify the fix took and nothing regressed

To use it with Claude Code, copy the skill directory into your repo (e.g. `.claude/skills/skillsaw-fix/`) or reference it from a marketplace, then ask the agent to "fix the skillsaw violations".

## The skillsaw-lint Skill

Where `skillsaw-fix` is reactive (violations were reported, fix them), the [`skillsaw-lint` skill](https://github.com/stbenjam/skillsaw/blob/main/skills/skillsaw-lint/SKILL.md) is the proactive guardrail: whenever an agent authors or modifies agentic context — a skill, slash command, agent, hook, plugin, or an instruction file like CLAUDE.md — it lints what it just wrote, applies autofixes, resolves the remaining violations with `skillsaw explain` guidance, and re-lints until clean before reporting the work done.

!!! note "Breaking changes (0.15)"
    Earlier releases shipped a built-in LLM fix path (`skillsaw fix --llm`, the `llm` config section, and the `skillsaw[llm]` extras) powered by LiteLLM. It was removed in 0.15 — coding agents already handle non-deterministic fixes better, with review built into the workflow. An existing `llm:` section in `.skillsaw.yaml` is now ignored with a warning. The long-deprecated `skillsaw lint --fix` flag was removed in the same release.

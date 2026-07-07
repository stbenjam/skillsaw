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

Examples: adding missing frontmatter, renaming files to kebab-case, registering unregistered plugins in marketplace.json, fixing skill names to match directory names. These are marked **SAFE** confidence and applied automatically.

Some fixes produce cascading changes — for example, renaming a skill name creates stale references in other files. These secondary fixes are marked **SUGGEST** confidence because simple name matching may replace occurrences that aren't actually skill name references. Use `--suggest --dry-run` to review these changes before applying them.

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

Installing the skillsaw plugin also registers a hint-only `PostToolUse` hook: when the agent edits an agentic-context file, the hook emits a short reminder to run `skillsaw-lint` on it. The hook never runs the linter itself — it only nudges.

!!! note "Breaking changes (0.15)"
    Earlier releases shipped a built-in LLM fix path (`skillsaw fix --llm`, the `llm` config section, and the `skillsaw[llm]` extras) powered by LiteLLM. It was removed in 0.15 — coding agents already handle non-deterministic fixes better, with review built into the workflow. An existing `llm:` section in `.skillsaw.yaml` is now ignored with a warning. The long-deprecated `skillsaw lint --fix` flag was removed in the same release.

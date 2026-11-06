## Why

Empty instruction files provide no guidance, and invalid UTF-8 prevents
skillsaw's content checks from reading them. This rule reports empty files
and read failures in `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `QWEN.md`, and
the other recognized instruction formats. It also checks discovered Codex
overrides, including those in APM source directories, and custom fallback
prose selected by `codex-instructions` analysis. Overrides need no analysis
configuration. These files are checked even when they also serve as a
command, agent, or skill; their existing roles and format checks remain
intact. Excluded and external content removed from the lint tree is not checked.
When a physical file has both configuration and prose roles, its retained prose
role still receives this validation. Files with only configuration roles do not.

Codex itself accepts empty files and decodes invalid UTF-8 with replacement
characters. This warning identifies missing guidance or text that skillsaw
cannot check; it does not mean Codex refuses to load the file. An empty
`AGENTS.override.md` can intentionally shadow `AGENTS.md` in that directory.

## Examples

**Bad:**

An empty `CLAUDE.md` file (0 bytes).

**Good:**

```markdown
# Project Rules

Run `make test` before committing.
Use Go 1.22+.
```

## How to fix

Save unreadable text as UTF-8. Add guidance to an accidental placeholder,
or remove it if it is not needed. Before removing an empty Codex override,
check whether it deliberately prevents another instruction file from loading.

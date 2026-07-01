## Why

When a skill is renamed, references to the old name in other files
(CLAUDE.md, other skills, configuration) become stale. The skill
loader will not find the old name, so any instruction referencing it
is silently broken.

## Examples

**Bad (skill renamed from `deploy` to `deploy-staging`):**

```markdown
Use the /deploy skill to ship to staging.
```

**Good:**

```markdown
Use the /deploy-staging skill to ship to staging.
```

## How to fix

Update references to the old skill name to use the new name. The
violation message identifies the stale reference and the current
skill name.

A name match in prose is not always a skill reference — a skill named
`api` renamed to `api-v2` does not make every mention of the word
"api" stale. Before rewriting a flagged line, verify the mention
actually refers to the skill (invocations like `/name`, paths like
`skills/name/`, or prose such as "the name skill") and leave generic
uses of the word alone.

`skillsaw fix --suggest` rewrites references automatically only when
the old name has at least `autofix-min-segments` hyphen-separated
segments (default 2) — multi-segment kebab-case names essentially
never collide with ordinary prose. Single-word names are reported but
never rewritten automatically; fix those by hand (or with a coding
agent) using the judgment above.

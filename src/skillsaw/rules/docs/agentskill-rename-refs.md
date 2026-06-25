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

Update all references to the old skill name to use the new name.
The violation message identifies the stale reference and the current
skill name. `skillsaw fix` can update these references automatically.

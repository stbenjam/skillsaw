## Why

When instruction files use "directory" in one place and "folder" in
another, the model may treat them as different concepts or waste tokens
reconciling them. Consistent terminology reduces ambiguity and helps the
model pattern-match instructions to the right context.

## Examples

**Bad (across files):**

```markdown
<!-- CLAUDE.md -->
Create a new directory under `src/`.

<!-- .claude/rules/testing.md -->
Put test fixtures in the `tests/` folder.
```

**Good:**

```markdown
<!-- Both files -->
Create a new directory under `src/`.
Put test fixtures in the `tests/` directory.
```

## How to fix

Pick the most common term across your instruction files and use it
everywhere. Prefer technical terms over informal ones (e.g., "directory"
over "folder", "repository" over "codebase"). A coding agent can
standardize terminology automatically.

If a group doesn't apply to your repository — for example, a polyglot
repo that legitimately documents both Go *functions* and Java *methods* —
disable just that group (or override its severity) while keeping the
rest enforced:

```yaml
rules:
  content-inconsistent-terminology:
    severity: error
    groups:
      function/method: off      # disable this group only
      PR/pull request/merge request: warning  # downgrade this group
```

Valid group names: `directory/folder`, `repo/repository/codebase`,
`PR/pull request/merge request`, `function/method`. Valid values: `off`
(or `false`) to disable, or a severity (`error`, `warning`, `info`).

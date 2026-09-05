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

Only running prose counts as a terminology choice. Headings (e.g. a
skill titled `# Create Pull Request` that says "PR" everywhere in its
body) and inline code spans (e.g. a path like `` `.planning/codebase/foo.md` ``)
are excluded, since they're a different register than the prose choice
this rule is checking.

The `function/method` group is off by default: Python functions, Go methods,
HTTP methods and research methods name different concepts. Enable it only
when your project's vocabulary treats these terms as interchangeable:

```yaml
rules:
  content-inconsistent-terminology:
    groups:
      function/method: info  # opt in to this group
```

Other groups use the rule's severity unless overridden. Disable a group
with `off` or `false`, or choose its severity independently:

```yaml
rules:
  content-inconsistent-terminology:
    severity: error
    groups:
      directory/folder: off
      PR/pull request/merge request: warning
```

Valid group names: `directory/folder`, `repo/repository/codebase`,
`PR/pull request/merge request`, `function/method`. Valid values: `off`
(or `false`) to disable, or a severity (`error`, `warning`, `info`).

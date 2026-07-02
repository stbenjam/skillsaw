## Why

A markdown link pointing to a nonexistent file is a dead reference —
the model cannot follow it to read context it was promised, and a human
reader clicking it gets a 404. Broken links typically appear after renames
or directory restructuring when the referencing file was not updated.

## Examples

**Bad:**

```markdown
See [setup guide](docs/old-setup.md) for installation steps.
```

**Good:**

```markdown
See [setup guide](docs/setup.md) for installation steps.
```

## How to fix

Update the link target to the file's current path. When the violation
includes a "did you mean" suggestion, that is a fuzzy match against the
repository — verify it is correct and apply it. The autofix is
suggest-confidence: a plain `skillsaw fix` skips it, so run
`skillsaw fix --suggest` to apply the suggested corrections, and review
the result before committing.

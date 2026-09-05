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

Only repository-relative targets are checked. Anchors (`#...`) and any
target carrying an RFC 3986 URI scheme — not just `http(s):` and
`mailto:`, but also application links like `app://` or `vscode://` —
are treated as external and never reported.

Suggested corrections preserve link labels, titles, queries and anchors. Destinations
with spaces or parentheses are percent-encoded so the corrected link remains
valid Markdown. Files edited after the finding was produced are left alone
when their original token span can no longer be verified.

Links such as `docs/setup.md?plain=1#install` are checked against the path
`docs/setup.md`. Query text and fragments remain unchanged if a typo in that
path receives a suggested correction. Exact existing filenames containing
`?` are also accepted on filesystems that support them.

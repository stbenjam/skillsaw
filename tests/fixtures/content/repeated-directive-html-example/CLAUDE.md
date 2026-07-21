# Rule-writing guide

Guidance for writing lint-rule documentation in this repository.

## Quoting examples

Wrap contrasting examples in Bad/Good tags so the docs renderer styles
them, and place the fenced example directly after the tag with no blank
line in between:

<Bad>
```markdown
Always run make test before pushing any changes.
```
</Bad>

<Good>
```markdown
Always run make test before pushing any changes.
Fix any failure before you push rather than rerunning CI.
```
</Good>

## Review

Check the rendered output locally before opening a pull request.

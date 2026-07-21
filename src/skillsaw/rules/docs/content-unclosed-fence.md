## Why

A code fence that is opened but never closed makes markdown parse
everything after it — headings, instructions, whole sections — as code.
Agents render the file the same way, so instructions below the fence
lose their structure, and every content-quality rule is blinded: prose
hidden inside the runaway fence is stripped as code before scanning, so
a file full of weak language or placeholders lints clean and can even
grade A+.

## Examples

**Bad:**

````markdown
Deploy with:

```bash
make deploy ENV=staging

## Rollback

Try to roll back quickly if possible.
````

The `bash` fence never closes, so the entire Rollback section is code —
invisible to the agent as instructions and to every content rule.

**Good:**

````markdown
Deploy with:

```bash
make deploy ENV=staging
```

## Rollback

Roll back with `make rollback ENV=staging` within 5 minutes.
````

## How to fix

Add the missing closing fence right after the last intended code line —
same character as the opener, in a run at least as long (a three-backtick
opener closes with three or more backticks, a four-backtick opener needs
four). The autofix appends the matching closer at the end of the file;
if the code block was meant to end earlier, move the appended closer up
to the right line.

Markdown bodies embedded inside a YAML host document (`.coderabbit.yaml`
`path_instructions`, promptfoo prompts) are still checked, but reported
as **not auto-fixable**: appending a closer at the end of the host file
would corrupt the YAML, so close the fence by hand inside the embedded
block.

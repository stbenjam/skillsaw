## Why

`.roomodes` defines Roo Code's project-level custom modes: the personas an
agent switches into, what each one is allowed to touch, and when an
orchestrator should hand work to it. Roo validates the whole document, so a
single defect is rarely local — a duplicate slug or an unrecognised tool
group fails validation and the file contributes no modes at all. Nothing
reports that; the mode picker is simply shorter than the file suggests.

The quieter failures are the ones that pass validation. A misspelled
optional key such as `whentouse` is ignored at runtime, so the mode loads
without the text an orchestrator reads before delegating to it. And
`browser` — a tool group Roo's own documentation still shows — is accepted
and then stripped before the mode is built, so a mode asking for it gets
nothing.

Roo Code (the VS Code extension) shut down in May 2026, so this file no
longer drives a running product for most repositories. It stays worth
linting because it is still committed, still describes real delegation
boundaries, and is still read by whatever picks the repository up next. That
is also why the checks are conservative — see Severity.

`.roomodes` is configuration, not prose, so the content rules never read it.
The prose Roo shipped alongside it — `.roorules`, `.roo/rules/**` and
`.roo/rules-<mode>/**` — is attached as instruction content and gets the
full content and security rule suite without a Roo-specific rule.

## Severity

An unparseable document is the one error: Roo loads no mode at all from it,
so every mode the file appears to declare is gone.

Everything else is a warning. Roo Code no longer runs, so a mode that would
not have loaded costs whoever migrates or reads the file next, not a build.

## Examples

**Bad** — a slug Roo rejects, a mode with no `roleDefinition`, a misspelled
tool group, and a `groups` that is a string rather than a list:

```yaml
customModes:
  - slug: docs writer
    name: Documentation Writer
    groups:
      - read
      - reed
  - slug: reviewer
    name: Reviewer
    groups: read
```

**Good**:

```yaml
customModes:
  - slug: docs-writer
    name: Documentation Writer
    roleDefinition: >-
      You are a technical writer maintaining the ingest service documentation.
    whenToUse: >-
      Use when the change is confined to Markdown under docs/.
    groups:
      - read
      - - edit
        - fileRegex: \.(md|mdx)$
          description: Markdown files only
```

## How to fix

- Give every mode a `slug`, a `name`, a `roleDefinition` and a `groups`
  list. All four are required; a mode missing one does not load.
- Spell slugs with letters, digits and hyphens only, and make each one
  unique within the file — Roo rejects a document whose slugs repeat, which
  costs every mode in it, not just the repeated one.
- Use the tool group names Roo's schema accepts: `read`, `edit`, `command`,
  `mcp`, `modes`, each at most once per mode. Use the pair form —
  `["edit", {fileRegex: ...}]` — to restrict a group to matching files. Drop
  `browser`: it is stripped before the mode is built.
- Check the spelling of optional keys against the ones Roo defines —
  `whenToUse`, `description`, `customInstructions` — because a key outside
  that set is silently ignored rather than reported.
- To require the field an orchestrator reads before delegating, turn on the
  option (it is off by default):

  ```yaml
  rules:
    roo-modes-valid:
      require-when-to-use: true
  ```

- If the modes are no longer used, delete the file rather than leaving a
  stale description of who may edit what.

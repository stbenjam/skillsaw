## Why

`marketplace.json` is the registry index for a plugin marketplace. If
it contains invalid JSON or is missing required fields, tools that
consume the marketplace cannot list or install plugins.

## Examples

**Bad:**

```json
{"plugins": []}
```

**Good:**

```json
{
  "name": "my-marketplace",
  "description": "Internal plugin marketplace",
  "owner": {"name": "platform-team"},
  "plugins": []
}
```

## How to fix

Fix the JSON syntax error or add the missing required fields reported
in the violation message.

Plugin entries are also validated: every entry needs a unique `name`
and a `source`. A string source is a path relative to the marketplace
root — it should start with `./` and must not be an absolute path or
escape the repository with `..`. An object source declares its type via the `source` field
(`github`, `url`, `git-subdir`, or `npm`) and must carry that type's
required fields (`repo`, `url`, `url` + `path`, or `package`
respectively).

When `metadata.pluginRoot` is set, it is prepended to relative
sources, so bare names like `"formatter"` are valid and the `./`
style nudge does not apply. The plugin root itself must be a string
and, like sources, must not be an absolute path (values like
`/tmp/plugins` are invalid) and must not escape the repository with
`..`.

## Escaping plugin directories

A `plugins/*` child whose resolved location falls outside the
repository root — a symlink pointing at a sibling checkout, for
example — is dropped from discovery, because autofix must never write
outside the checkout. This rule reports the drop as a warning so the
plugin cannot lose all rule coverage silently: move the plugin inside
the repository (or vendor a copy) to restore coverage.

## Codex marketplaces

A Codex catalog at `.agents/plugins/marketplace.json` is validated by
`codex-marketplace-json-valid`, not by this rule: the two schemas
disagree, and Codex's `{"source": "local", "path": "./x"}` would be
reported here as an unknown source type on every entry. This rule
raises neither "Marketplace file not found" nor an unknown-source error
on a repository whose catalog is Codex's.

The legacy path `.claude-plugin/marketplace.json`, which Codex also
reads for backward compatibility, stays with this rule. A Codex-schema
catalog written to *that* path will be checked against the Claude
schema and will report a missing `owner` and an unknown `local` source
type — move it to `.agents/plugins/marketplace.json`.

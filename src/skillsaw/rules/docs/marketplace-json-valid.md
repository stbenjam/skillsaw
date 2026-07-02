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

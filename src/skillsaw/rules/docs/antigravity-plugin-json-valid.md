## Why

An Antigravity plugin conventionally lives under a customization root at
`.agents/plugins/<name>/`, or the `.agent/`, `_agents/`, `_agent/` equivalents.
A `plugins.json` entry or inherited registry can also name a plugin elsewhere
in the repository. Both require `plugin.json`. A standalone package at the
lint root is also recognized when its manifest declares
`"$schema": "https://antigravity.google/schemas/v1/plugin.json"`.
Use `--type antigravity-plugin` to check an existing root manifest without
that declaration, including a malformed document. A collection with no root
manifest does not acquire a missing-root-manifest finding.

Measured against `agy` 1.1.25: a directory whose manifest does not parse is
not loaded as a plugin at all. Its skills, agents, commands, rules, hooks and MCP servers all go
unread, and the only trace is one line in the debug log.

That is why a type error here is an error rather than a style note: the cost
is the whole package, not the field.

The manifest is a protobuf JSON message with exactly four fields that carry
meaning — `name`, `description`, `disabled`, `logo`. Every other key,
`$schema` and `version` and `author` included, is discarded as unknown and
the plugin still loads, so none of them is reported.

## Severity

**Errors** — the directory is not a plugin:

- `plugin.json` is missing, or is not a regular file.
- Invalid JSON, including an unpaired Unicode surrogate escape in any
  string or key, even inside discarded metadata.
- A repeated known root field (`name`, `description`, `disabled`, `logo`).
  Neither copy wins, including when one or both values are `null`.
- A UTF-8 byte-order mark (BOM). Remove it; the loader does not strip it.
- A root that is not a JSON object.
- A type error on one of the four fields: `name`, `description` and `logo`
  must be strings, `disabled` a boolean.

**Warnings** — the plugin loads in place but cannot be installed:

- A `name` outside `[A-Za-z0-9_-]`, or one beginning with a dot.
  `agy plugin install` refuses `Bad Name`, `a/b`, `../esc` and `.hidden`;
  discovery does not.

**Info**:

- No canonical `name`. Runtime discovery falls back to the directory name.
  Add `name` for consistent behavior across consumers. The separate
  installer accepts capitalized `Name`, which the runtime ignores; this
  advisory does not claim every missing canonical name prevents installation.

## What is not reported

- **Unknown keys and their duplicates.** `$schema`, `version`, `author`, `homepage`, `license`,
  `keywords`, `entrypoint` and everything else are discarded by the parser
  and cost nothing. A package written to the portable Agent Plugins schema
  and dropped into `.agents/plugins/` is claimed and loaded by Antigravity
  unchanged, and this rule says nothing about it.
- **A `$schema` value.** The URL the vendor tells authors to write,
  `https://antigravity.google/schemas/v1/plugin.json`, is 404, so there is
  nothing to dereference. The schema itself is published inline under
  "Full JSON Schema" at `https://antigravity.google/docs/cli/plugins/`,
  and is narrower than what `agy` loads — it lists only `name` and
  `description`, while `disabled` and `logo` load fine — so this rule
  follows the loader rather than the schema.
- **Capitalized fields.** Runtime fields match exactly: `Description`,
  `Disabled` and `Logo` are unknown metadata. This ProtoJSON behavior differs
  from Antigravity's hooks, MCP and registry readers.
- **`disabled: true`.** It is the documented way to keep a plugin in the
  tree without loading it.
- **A `null` value, and an empty string in a string field.** protojson
  decodes both as the field's default, so each reads as the key being
  absent: `{"name": null}`, `{"name": ""}` and no `name` at all give the
  same finding and the same directory-name fallback. `disabled` is the
  exception — it is a boolean, and `""` there is `invalid value for bool
  field disabled`, so the directory is not a plugin.

## Examples

**Bad** — `name` written as a number, so nothing in the directory loads:

```json
{
  "name": 42,
  "description": "Berth allocation helpers"
}
```

**Good**:

```json
{
  "name": "berth-tools",
  "description": "Berth allocation helpers: a status command, an allocation reviewer, and the simulator MCP server.",
  "logo": "assets/berth-tools.png"
}
```

## How to fix

- Give `name` a string of letters, digits, `-` and `_`, matching the
  directory name.
- Give `description` a sentence saying when the plugin is worth loading —
  it is what a reader sees before the components.
- Write `disabled` as a boolean, not `"no"` or `0`.
- Remove repeated known root fields. A repeated `name`, for example, fails
  with `proto: duplicate field "name"`. Repeated unknown metadata is accepted.

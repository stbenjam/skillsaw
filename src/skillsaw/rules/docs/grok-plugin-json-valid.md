## Why

`.grok-plugin/plugin.json` is what Grok Build reads to register a plugin and
to find the components it ships. A manifest is optional — a directory
holding `skills/`, `agents/`, `hooks/hooks.json` or `.mcp.json` installs
without one — but a manifest that *is* there and fails to load takes the
whole directory with it. Measured against Grok Build 1.0.13: a plugin with
a malformed manifest and a real `skills/` directory installed with
`Installed 1 plugin(s)` and exit 0, and `grok inspect` then reported
`plugins: []`. Nothing connects the two.

The declared component paths fail more quietly still. A path that escapes
the plugin root or does not exist is dropped with no diagnostic, and `grok
plugin validate` calls the manifest valid either way.

A finding names the manifest Grok actually reads, which is not always
`.grok-plugin/plugin.json`. Grok resolves the first of `plugin.json`,
`.grok-plugin/plugin.json`, `.claude-plugin/plugin.json` that exists — the
**reverse** of the catalog order — so on a plugin carrying more than one, or
on a manifest-less directory a catalog claims, the file to open is the one
the finding names.

## Severity

A finding's severity is how much of the plugin the defect costs.

**Errors** — Grok skips the whole plugin directory at discovery. The
conventional `skills/` does not rescue it.

- Invalid JSON, including a bare `NaN`, `Infinity` or `-Infinity` token and
  a duplicated key. Grok's parser refuses all three: `grok plugin validate`
  on a manifest repeating `name` reported ``duplicate field `name` `` and
  exit 1. A duplicated key Grok's loader does not read is tolerated by the
  binary and still reported here — two values for one key is a defect
  whichever key it is.
- A manifest that is not a JSON object.
- `name` missing, not a string, or empty.
- A `name` outside Grok's own rule, whose message this one quotes: 1-64
  chars, lowercase alphanumeric and hyphens, no leading or trailing hyphen.
  Consecutive hyphens and digits-only names are legal.

**Warnings** — the plugin loads and one component list is silently lost.

- A declared `skills`, `commands`, `agents`, `hooks` or `mcpServers` path
  that is absolute, contains `..`, or resolves outside the plugin through a
  symlink. Containment is enforced rather than incidental: a target that
  exists outside the plugin and holds a real `SKILL.md` still loads
  nothing. The two lexical shapes are refused whether or not they normalise
  back inside — the field is no place for either.
- A declared path that is not in the plugin.
- A declared path of the wrong kind: `skills`, `commands` and `agents` name
  directories, `hooks` and `mcpServers` name files.
- A declared path that is the empty string.
- `hooks` or `mcpServers` given as an array. Each is *one* path or *one*
  inline object: a list-valued `hooks` loaded as an empty inline document
  with no target, and a list-valued `mcpServers` loaded no servers at all.
- A `skills`, `commands` or `agents` override while the conventional
  directory beside it holds files. Grok **replaces** the conventional
  directory rather than adding to it, so `"skills": ["extra"]` drops
  everything under `skills/`. The official catalog tool unions the two, so a
  plugin that passes it still loses them at runtime.

**Info** — metadata the marketplace browser shows.

- A `version` that is not a semantic version.
- A missing `description`.

## What is never reported

Each of these was measured as harmless, and reporting it would be a false
positive on a plugin that works:

- A `name` that disagrees with the directory name. The manifest name wins
  everywhere — install, `plugin list`, `inspect`, and skill attribution.
- An unknown manifest key.
- A bare string where an array of paths is allowed. `skills`, `commands` and
  `agents` each accept either.
- A `version` that is not a string. Nothing measured says what the loader
  does with one, and guessing would report a defect that may not exist.
- `hooks` or `mcpServers` given as a string. Both fields are *a path or the
  object itself*, so a string naming no file is reported as a path that is
  not in the plugin, never as a type error.

## Examples

**Bad** — the override costs every skill under `skills/`, and the manifest
loads without complaint:

```json
{
  "name": "tide-charts",
  "version": "1.1.0",
  "description": "Shoreline survey windows from NOAA tide predictions.",
  "skills": ["./extra-skills"]
}
```

**Good** — the conventional directory is named alongside the extra one:

```json
{
  "name": "tide-charts",
  "version": "1.1.0",
  "description": "Shoreline survey windows from NOAA tide predictions.",
  "skills": ["./extra-skills", "./skills"]
}
```

## How to fix

- Give the manifest a `name` Grok accepts, and let it differ from the
  directory name if that reads better — the manifest name is the one
  everything uses.
- List the conventional directory alongside an override, or move the
  components into the directory the override names.
- Point every declared path at something inside the plugin, and check it
  exists: nothing at runtime will tell you it does not.
- Add a `description`, and a semantic `version`, for the marketplace
  browser.

A repository that generates a component directory during its build has
paths that are not on disk when skillsaw runs. Rather than turning the rule
off, drop the existence check:

```yaml
rules:
  grok-plugin-json-valid:
    check-paths-exist: false
```

A repository that keeps its conventional directories deliberately empty —
or ships nothing under them — loses nothing to an override, and can drop
that finding alone:

```yaml
rules:
  grok-plugin-json-valid:
    check-overrides: false
```

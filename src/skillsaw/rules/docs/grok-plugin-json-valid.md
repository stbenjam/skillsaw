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

## Severity

A finding's severity is how much of the plugin the defect costs.

**Errors** — Grok skips the whole plugin directory at discovery. The
conventional `skills/` does not rescue it.

- Invalid JSON.
- A manifest that is not a JSON object.
- `name` missing, not a string, or empty.
- A `name` outside Grok's own rule, whose message this one quotes: 1-64
  chars, lowercase alphanumeric and hyphens, no leading or trailing hyphen.
  Consecutive hyphens and digits-only names are legal.

**Warnings** — the plugin loads and one component list is silently lost.

- A declared `skills`, `commands`, `agents`, `hooks` or `mcpServers` path
  that escapes the plugin root, whether by `..`, by being absolute, or
  through a symlink. Containment is enforced rather than incidental: a
  target that exists outside the plugin and holds a real `SKILL.md` still
  loads nothing.
- A declared path that is not in the plugin.
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

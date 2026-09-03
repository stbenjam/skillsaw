## Why

`.codex-plugin/plugin.json` is the required entry point for an OpenAI
Codex plugin. Codex reads the plugin's name from it and resolves every
bundled component through it, so a manifest that names a path outside the
plugin root — or a path that does not ship — installs a plugin whose
skills, hooks or assets silently never load.

## Examples

**Bad:**

```json
{
  "name": "note_taker",
  "skills": "../shared-skills/",
  "interface": {"logo": "assets/logo.png"}
}
```

**Good:**

```json
{
  "name": "note-taker",
  "version": "1.2.0",
  "description": "Capture meeting notes and turn them into follow-ups.",
  "skills": "./skills/",
  "interface": {"logo": "./assets/logo.png"}
}
```

## How to fix

Add the missing field, or correct the path the violation names.

`name` is required and should be kebab-case — plugin hosts use it as the
plugin identifier and component namespace. `version` and `description`
are reported as recommended; adjust `recommended-fields` to change that
set.

Manifest paths (`skills`, `apps`, `hooks`, and `mcpServers` when
path-valued) must resolve inside the plugin root and should start with `./`.
Interface asset fields (`composerIcon`, `logo`, `logoDark`, `screenshots`) accept
remote HTTP/HTTPS URLs and data URIs as well as local relative paths. When given
as local paths, they must also resolve inside the plugin root and should start
with `./`. An absolute path or one containing `..` is an error; a missing `./`
prefix on a local path is informational. Paths that point at something not in the
repository are reported as warnings — set `check-paths-exist: false` to skip that
check when assets are generated at build time.

`mcpServers` is not purely a path field: it accepts a path string, an
inline server object, or an array mixing both. Only its path-valued
entries get the path checks; inline objects are linted as MCP server
configuration.

`author` must be a string or an object (an object should carry a
`name`); any other type is an error. `interface` must be an object —
another type is a warning, and its documented fields are then checked
individually. An empty string in a path field is an error (there is
nothing to resolve), and a non-string value in one is a warning.

A path can also exist and still be reported for its *kind*: `hooks` and
a path-valued `mcpServers` name a file and are warned about when they
resolve to a directory, and `skills` names a directory and is warned
about when it resolves to a file. The path is fine — point the field at
the right kind of filesystem object. Other path fields (`apps`, and local
`interface` asset paths) are checked for containment and existence but
not for kind, because Codex accepts more than one shape for them. Remote
interface asset URLs are not resolved as local paths or checked for
repository existence.

`version` can be any valid version string; semver is recommended but not enforced.

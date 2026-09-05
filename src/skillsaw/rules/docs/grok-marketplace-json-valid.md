## Why

`.grok-plugin/marketplace.json` is the catalog Grok Build uses to discover, list,
and install plugins across repositories.

This rule checks the catalog decoder and local paths, with a configurable
policy for remote commit pins:

- When a catalog is well-formed, Grok lists all declared plugins. If the file has
  syntax errors or invalid typed fields, Grok falls back to searching only
  the default `plugins/` directory, which can cause plugins located in other
  directories to be missed.
- For individual entries, specifying valid `name`, `source`, and directory
  paths ensures each plugin is registered properly in the catalog.
- For remote Git sources, pinning entries with a commit `sha` ensures reproducible,
  secure installations for everyone using your marketplace.

This rule validates `.grok-plugin/marketplace.json`. Catalogs targeting Claude
Code (`.claude-plugin/marketplace.json`) are checked separately by
[`claude-marketplace-json-valid`](claude-marketplace-json-valid.md).

## Severity

Findings distinguish between structural errors and upstream recommendations:

**Errors** — catalog or entry load failures, and the configured commit-pin policy:

- Invalid JSON syntax, a leading UTF-8 BOM, or non-finite number tokens
  (`NaN`, `Infinity`, `-Infinity`).
- Duplicate recognized catalog, entry, owner, or author fields.
- Missing or non-string catalog `name`, or invalid known field types.
- A present `plugins` value that is not an array.
- Missing catalog file when explicitly linting with `--type grok-marketplace`.
- Plugin entries that are not JSON objects.
- Missing or invalid `source` (must be a path string or source object).
- Missing or non-string plugin entry `name`.
- Duplicate resolved plugin names within the same catalog.
- Local `source.path` pointing to a directory that does not exist under the
  marketplace root.
- Local `source.path` that is absolute, contains `..`, or resolves outside the
  marketplace root, or contains an empty or current-directory component.
  The root spellings `.` and `./`, trailing or repeated separators, and
  colon-containing components are not valid catalog paths.
- A source object's non-null `type`, `source`, `url`, `path`, `ref`, or `sha` that is not a string.
- Remote Git source missing a commit `sha`, when the rule's `require-sha` policy is enabled.
- Remote Git source with an invalid `sha` (must be a 40- or 64-character hex
  string).

The catalog decoder distinguishes optional fields from defaulted arrays:

| Field | Accepted values |
| --- | --- |
| Catalog `name` | Required string; empty is accepted |
| Catalog `description` | String, null, or omitted |
| Catalog `owner` | Object, null, or omitted; the object requires string `name` and accepts optional nullable string `email` |
| Catalog `plugins` | Array of objects; omission defaults to an empty array, but null is invalid |
| Entry `name` | Required string; empty is accepted |
| Entry `version`, `description`, `category`, `homepage` | String, null, or omitted |
| Entry `author` | Object, null, or omitted; the object requires string `name` |
| Entry `tags`, `keywords`, `domains` | Arrays of strings; omission defaults to empty arrays, but null is invalid |
| Entry `source` | String, object, null, or omitted; null or omission leaves the entry without a loadable source |

A bad typed field rejects the entire catalog, including valid sibling entries.
The rule reports those errors before installation advice. Index parity also
stands down for that rejected catalog. Diagnostic discovery retains declared
Grok content so metadata errors do not reclassify it as another host's content.

**Warnings** — catalog format advisories:

- Remote Git source `path` that fails the same relative-subdirectory grammar,
  such as `.` or `plugins/almanac/`. Grok refuses that subdirectory during
  installation; this check retains its existing warning severity.
- A `source` object that specifies neither `path` nor `url`.

**Info** — style and upstream compatibility tips:

- A commit `sha` using uppercase hex characters or a 64-character SHA-256 hash.
  While Grok Build's runtime accepts both, official marketplace submission
  validators (such as `xai-org/plugin-marketplace`) recommend 40-character
  lowercase SHA-1 hashes.

## What is not reported

- **Source discriminators**: a non-null `url` selects a remote source. With
  an absent or null URL, Grok reads the local `path` regardless of `type` or
  `source` tags. An empty URL remains remote and is reported as unusable.
- **Path separators**: Grok accepts slash or backslash separators between
  directory names. It removes one leading `./` before parsing; a leading
  `.\` is not equivalent.
- **Empty names**: empty string catalog and entry names pass decoding. A local
  plugin is listed under its effective manifest name. Display-index keys still
  use the catalog entry's literal name.
- **Empty catalogs**: omitting `plugins` or using an empty array is valid and
  suppresses conventional `plugins/` fallback discovery.
- **Unknown metadata keys**: custom catalog, entry, owner, and author members
  are ignored, including duplicates.
- **Source object duplicates**: the last value is effective, but every occurrence
  must have the accepted type. A valid later value cannot repair an earlier
  non-string value. This differs from duplicate recognized struct fields.

## Examples

**Bad** — unpinned Git source and missing local plugin directory:

```json
{
  "name": "harbour-plugins",
  "plugins": [
    {
      "name": "almanac",
      "source": {"source": "url", "url": "https://github.com/harbour-example/almanac.git"}
    },
    {
      "name": "tide-charts",
      "source": {"type": "local", "path": "./plugins/tides"}
    }
  ]
}
```

**Good** — pinned remote Git source and valid local path:

```json
{
  "name": "harbour-plugins",
  "plugins": [
    {
      "name": "almanac",
      "description": "Sunrise, sunset and civil twilight for a survey date.",
      "source": {
        "source": "url",
        "url": "https://github.com/harbour-example/almanac.git",
        "sha": "1f9d0c73a86b24e5107cad3f88b90250e6c147da"
      }
    },
    {
      "name": "tide-charts",
      "description": "NOAA tide predictions turned into shoreline survey windows.",
      "source": {"type": "local", "path": "./plugins/tide-charts"}
    }
  ]
}
```

## How to fix

- Pin remote Git sources with a 40-character lowercase commit hash.
- Ensure local `source.path` references point to existing subdirectories of
  the marketplace root, the directory containing `.grok-plugin/`. Use
  `./packages/almanac` or `packages/almanac`, with no trailing or repeated
  separator. Place a root plugin in a subdirectory before cataloging it;
  `.` and `./` are not supported catalog sources.
- Apply the same path grammar to remote `source.path` values, relative to
  the cloned repository. Omit the path or use null for the whole clone.
  Plugin manifest component paths use a separate contract.
- Ensure every entry has a `name` and resolves to a unique plugin name. For
  local plugins, duplicate checks compare the name declared in each plugin's
  manifest rather than the catalog entry's declared `name`.
- Place your Grok marketplace catalog at `.grok-plugin/marketplace.json`.

If your marketplace intentionally tracks a branch rather than pinned commits,
you can relax the commit SHA requirement:

```yaml
rules:
  grok-marketplace-json-valid:
    require-sha: false
```

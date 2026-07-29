# APM (Agent Package Manager)

<!-- Repo-root-relative src/... and cross-reference paths below are intentionally kept as prose, not navigable links. -->
<!-- skillsaw-disable content-unlinked-internal-reference -->

## Upstream source(s)
- Repo: https://github.com/microsoft/apm — Microsoft's Agent Package Manager (npm-like
  dependency manager for AI agents).
- Docs / spec: https://microsoft.github.io/apm/

## What to check
- `apm.yml` manifest: required fields (skillsaw checks `name`, `version`, `description`)
  and any newly required keys.
- `.apm/` directory layout: primitive subdirectories skillsaw recognizes (`skills/`,
  `instructions/`, `prompts/`, `agents/`, `context/`, `hooks/`, `extensions/`) and any
  new package/primitive types (plugins, MCP servers).
- `apm.lock.yaml` lockfile shape (skillsaw does not yet validate it — note if that gains
  a required structure).

## skillsaw rules that map
Package `src/skillsaw/rules/builtin/apm/`:
- `apm-yaml-valid` — `apm/yaml_valid.py` (`apm.yml` exists + valid YAML + required fields)
- `apm-structure-valid` — `apm/structure_valid.py` (an existing `.apm/` contains a
  recognized primitive subdirectory; each `.apm/skills/*/` has a `SKILL.md`)

## Sync notes
- `yaml_valid.py` hand-copies the required-field list (`name`, `version`, `description`)
  — re-check against the manifest spec.
- `structure_valid.py` hand-copies the expected `.apm/` subdirectory names — re-check
  against the current directory layout.
- Both rules gate on `context.has_apm`; they auto-enable only for APM repos.
- `has_apm` is true for a root `apm.yml` alone, which covers consumer manifests that
  only install dependencies. `structure_valid.py` therefore checks nothing unless an
  `.apm/` source directory exists (issue #472) — keep that distinction if the layout
  rules grow.

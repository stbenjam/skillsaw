## Why

A customization root can carry registry files — `agents.json`,
`plugins.json`, `skills.json`, `workflows.json` — that name *where else* to
load that kind of customization from. They hold no customizations
themselves:

```json
{ "entries": [{ "path": "internal/schedule/agents" }] }
```

Measured against `agy` 1.1.25: a registry whose root is not an object logs
one `Failed to load JSON config file` line and is skipped, and `agy` exits
0. Nothing else reports it, so a mistyped registry looks exactly like a
project that has none — the agents or skills it was meant to add are simply
absent.

## Opt-in

Off by default. Only `agents.json` and `plugins.json` could be exercised
against a running `agy`: no offline subcommand loads the other two, so the
checks stop at what a measurement covers rather than guessing at a schema.
Turn it on when a repository actually uses these files.

```yaml
rules:
  antigravity-config-json-valid:
    enabled: true
```

## Severity

**Errors** — the registry is skipped and loads nothing:

- Invalid JSON, or a non-finite number (`NaN`, `Infinity`, `-Infinity`).
- A root that is not a JSON object.
- `entries` present but not an array.
- An `entries` element that is not an object, or that has no string `path`.
  One finding names the first few positions rather than one per entry: a
  registry written to the wrong shape is wrong in every entry.

## What is not reported

- **Whether a `path` resolves.** A path is absolute, `~/`-relative, or
  relative to the repository root, and a registry may legitimately name a
  directory that only exists on a developer's machine.

  skillsaw still *follows* the ones that do resolve inside the repository.
  A `plugins.json` entry's plugins get their hooks, MCP servers, skills and
  prose linted, and an `agents.json` entry's `*.md` is read as agent prose —
  independently of this rule, which is opt-in. `include_only` and `exclude`
  are ignored when deciding what to lint: skillsaw reports what a
  repository ships, not what it currently loads.
- **`include_only` and `exclude` shapes.** Neither was reachable offline.
- **Unknown keys.** Antigravity reads these files with a tolerant JSON
  decoder that discards them.
- **A repeated key.** The same decoder takes the last value: an `entries`
  key or a `path` written twice loads the second one's directory.

## Examples

**Bad** — an array root, which Antigravity skips whole:

```json
[{ "path": "internal/schedule/agents" }]
```

**Good**:

```json
{
  "entries": [
    {
      "path": "internal/schedule/skills",
      "include_only": ["gtfs-*"]
    }
  ],
  "inherits": [{ "path": "~/.gemini/config" }]
}
```

## How to fix

- Wrap the list in an object under `entries`.
- Give every entry a string `path` pointing at the directory of items
  itself. A parent directory loads nothing — the path must name the
  directory the agents, skills or plugins sit directly inside.

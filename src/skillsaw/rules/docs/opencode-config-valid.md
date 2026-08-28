## Why

`opencode.json` is where an OpenCode project declares its MCP servers, its
agents and its slash commands. It ships in the repository, and every one of
those settings fails quietly: OpenCode reads the file, does not find the key
it wanted, and carries on with a default. An MCP server whose `command` was
written as a string rather than an argv array simply never starts, and
nothing says so.

OpenCode is mid-rename. Version 2.0 renames a large part of the
configuration — `agent` becomes `agents`, `command` becomes `commands`,
`permission` becomes `permissions`, and MCP servers move one level down
under `mcp.servers` — while continuing to load the 1.x spelling, which it
normalizes in memory. **Both spellings are valid here.** This rule never
reports a 1.x key as an error, and a project can migrate on its own
schedule.

What it does report is a file that declares *both* spellings of one
setting. OpenCode folds the old key into the new one, so the setting arrives
twice and which copy survives depends on merge order — a coin flip written
into a config file.

The MCP servers in this file also reach [`mcp-prohibited`](mcp-prohibited.md)
and the rest of the ecosystem-neutral policy rules, in either the 1.x flat
shape or the 2.0 nested one. [`mcp-valid-json`](mcp-valid-json.md) stands
aside for OpenCode: its transports are named for where the server runs
(`local`/`remote`) rather than for the wire protocol, and a Claude-shaped
check would report a correct OpenCode config as broken.

## Severity

Three findings are errors by default:

- The file does not parse, so nothing in it is in effect. Comments and a
  trailing comma are *not* parse errors — OpenCode reads both `.json` and
  `.jsonc` through a JSONC parser, and so does skillsaw.
- The file parses but its top level is an array or a scalar rather than an
  object, which OpenCode cannot read as configuration either.
- An MCP server's `environment` or `headers` map holds a real-looking
  credential, which is now committed.

A fourth credential case is reported by
[`mcp-valid-json`](mcp-valid-json.md) rather than here: an MCP `url`
carrying user information, as in `https://user:pass@host/mcp`. `url` means
the same thing in every host's dialect, so that one check stays in the
ecosystem-neutral rule even though the rest of the shape check defers here.

Shape problems are warnings, because the rest of the file still loads: a
missing or unknown `type`, a `command` that is not a non-empty array of
strings, a non-string or empty `url`, an `environment` or `headers` that is
not an object, a `timeout` that is neither a number nor an object of
`startup`/`catalog`/`execution`/`request`, a non-boolean
`enabled`/`disabled`, an agent or command entry that is not an object, a
`template` that is not a non-empty string, both spellings of one renamed
key, and a server declared under both layouts at once.

Two `$schema` findings are also warnings: a `$schema` that is not a string,
and one pointing at `https://opencode.ai/tui.json`, which describes
`tui.json` rather than this file.

Information-level findings never fail a build:

- An unrecognized top-level key. OpenCode's schema changes weekly, so a key
  this release has not heard of is more likely new than wrong — `extra-keys`
  accepts it without waiting for a skillsaw release.
- An unrecognized key on an MCP server. Same reasoning, same remedy:
  `extra-keys` covers these too.
- A `$schema` that is neither the documented URL nor the TUI one. A vendored
  or mirrored copy is legitimate, so this is a note rather than a defect.

## Examples

**Bad** — a Claude-shaped MCP server in an OpenCode config, and a file that
declares one setting twice:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "agent": { "reviewer": { "prompt": "Review this change." } },
  "agents": { "reviewer": { "system": "Review this change." } },
  "mcp": {
    "playwright": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@playwright/mcp@latest"]
    }
  }
}
```

`type: "stdio"` is not a transport OpenCode knows, `command` must be the
argv array, there is no `args` key, and `agent`/`agents` both define
`reviewer`.

**Good, 1.x spelling** — comments and a trailing comma are fine:

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  // Local servers are spawned directly, so command is argv.
  "mcp": {
    "playwright": {
      "type": "local",
      "command": ["npx", "-y", "@playwright/mcp@latest"],
      "enabled": true,
    }
  },
  "agent": {
    "reviewer": {
      "description": "Reviews a diff for correctness bugs",
      "prompt": "Review this change.",
      "disable": false
    }
  }
}
```

**Good, 2.0 spelling** — the same configuration after migrating:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servers": {
      "playwright": {
        "type": "local",
        "command": ["npx", "-y", "@playwright/mcp@latest"],
        "disabled": false,
        "timeout": { "catalog": 30000, "execution": 30000 }
      }
    }
  },
  "agents": {
    "reviewer": {
      "description": "Reviews a diff for correctness bugs",
      "system": "Review this change.",
      "disabled": false
    }
  }
}
```

## How to fix

- Give every MCP server a `type` of `local` or `remote`. A `local` server
  needs `command` as a non-empty array of strings; a `remote` server needs a
  `url`.
- Pick one spelling per setting. Keep `agent` or `agents`, `prompt` or
  `system`, `enabled` or `disabled` — never both. `enabled` and `disabled`
  are the same switch with the sense inverted, so a server carrying both is
  saying two different things.
- Replace a committed credential with OpenCode's substitution syntax:

  ```json
  { "headers": { "Authorization": "Bearer {env:MY_API_KEY}" } }
  ```

  `{env:VAR}` and `{file:./path}` both work, and skillsaw recognises them as
  placeholders.

- For a key newer than this skillsaw release, accept it without waiting.
  One list covers both places a key can be unrecognized — the top level and
  an MCP server entry:

  ```yaml
  rules:
    opencode-config-valid:
      extra-keys:
        - somethingNew      # a new top-level key
        - codemode          # a new key on an MCP server
  ```

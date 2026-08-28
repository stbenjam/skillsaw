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
setting. The setting then arrives twice and one copy is ignored — and which
copy that is depends on *where* the pair sits, not on key order.

The finding never names the surviving value. Which copy survives depends on
the section the pair sits in *and* on the release doing the reading, and the
file records only the first. A top-level 1.x key makes OpenCode 2.0 read the
whole document as a 1.x config, so the 2.0 key drops — but `autoshare`/`share`
and `reference`/`references` are declared on both halves of the 1.x schema, so
that reasoning does not reach them. Under the 2.0 `agents` section it is the
*2.0* field that survives. An MCP server's `enabled`/`disabled` resolves one
way when a 1.x binary lowers a 2.0-shaped file and the other way when a 2.0
binary reads a nested `mcp.servers` entry.

So the message says only that one of the two values is in effect. Either key
alone is valid, so keeping one and deleting the other is the fix whichever
one survives — and saying nothing is better than naming the wrong one, which
would point you at deleting the value that is live.

The MCP servers in this file also reach [`mcp-prohibited`](mcp-prohibited.md)
and the rest of the ecosystem-neutral policy rules, in either the 1.x flat
shape or the 2.0 nested one. [`mcp-valid-json`](mcp-valid-json.md) stands
aside for OpenCode: its transports are named for where the server runs
(`local`/`remote`) rather than for the wire protocol, and a Claude-shaped
check would report a correct OpenCode config as broken.

## Severity

One finding is an error here: the file parses, but its top level is an array
or a scalar rather than an object, so OpenCode has no configuration to read.

The other errors an OpenCode config can draw come from
[`mcp-valid-json`](mcp-valid-json.md) instead, because they hold whatever
dialect a file is written in. Keeping them there is deliberate: this rule
carries a `since`, so a project still pinning an older `version:` — the
ordinary state right after an upgrade — would otherwise have them gated off.

- The file does not parse, so nothing in it is in effect. Comments and a
  trailing comma are *not* parse errors — OpenCode reads both `.json` and
  `.jsonc` through a JSONC parser, and so does skillsaw.
- An MCP server has a committed credential: a `url` carrying user
  information, as in `https://user:pass@host/mcp`, or a real-looking value in
  the server's `environment`, `headers` or `oauth` map. The 1.x camelCase
  OAuth keys are normalized before the credential-name test, so a literal
  `clientSecret` is recognized as one.

Shape problems are warnings, because the rest of the file still loads: a
missing or unknown `type`, a `command` that is not a non-empty array of
strings, a non-string or empty `url`, an `environment`, `headers` or `oauth`
that is not an object — `oauth: false` is the documented way to switch OAuth
off, so that one is valid — a `timeout` that is neither a number nor an
object of `startup`/`catalog`/`execution`/`request`, a non-boolean
`enabled`/`disabled`, an agent or command entry that is not an object, a
`template` that is not a non-empty string, both spellings of one renamed key
(including the 1.x and 2.0 OAuth field names), and a server declared under
both layouts at once.

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
`reviewer`. The unknown transport is reported first and on its own: the rest
of a server's shape depends on which transport it is, so those checks resume
once `type` is fixed and the file is linted again.

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
        - elicitation       # a new key on an MCP server
  ```

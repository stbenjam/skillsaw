## Why

`mcp_config.json` in a customization root — `.agents/`, `.agent/`,
`_agents/` or `_agent/` — or in an Antigravity plugin declares the MCP
servers the agent can call. Each one is a process Antigravity spawns or an
endpoint it connects to, so what the file says is what the agent can reach.

Its two failure modes are far apart, and neither is visible from the file.
Measured against `agy` 1.1.26:

- A **JSON syntax error, a non-null root that is not an object, or a
  non-null `mcpServers` value that is not an object** is startup-fatal.
  `agy` prints one message naming the file and exits 1; no session starts.
- A **per-server shape problem drops that server, silently**. There is no
  diagnostic and no exit code. The tools that server was meant to provide
  are simply absent, and the most likely way to notice is an agent
  improvising around a tool it cannot see.

This rule reports both and says which one a finding is.

`mcp-valid-json` stands its own shape walk down for this file, because
Antigravity's dialect is its own — `serverUrl` is a remote form beside
`url`, and it wins over `command` when both are present, while a server
with no connection field at all is legal. What it keeps are the
checks no dialect changes: a connection URL carrying user information, and
a credential written into `env`, `headers`, `oauth`, or a server's own
`clientId` / `clientSecret`. It keeps those even when this rule is turned
off. The parse failure is *this* rule's — one defect, one finding — and
goes unreported while this rule is off, because a user who pinned a
`version:` past this release should see the results that release had.

## Severity

**Errors** — Antigravity exits 1 and no session starts:

- Invalid JSON: a syntax error, a comment, a trailing comma, or a non-finite
  number (`NaN`, `Infinity`, `-Infinity`). The parser is strict JSON.
- A UTF-8 byte-order mark (BOM) before the JSON document.
- A non-null root or `mcpServers` value that is not an object.

**Warnings** — a missing server, a dropped server, or an empty command:

- An absent or null `mcpServers` object, including a null document. A bare map of servers is the shape several other
  hosts accept; here it is read as an ordinary document with no servers in
  it, so the file is inert rather than broken.
- A non-null server that is not an object.
- Non-null `env` or `headers` that is not an object, or a value that is
  neither a string nor null.
- Non-null `oauth` that is not an object, or a `clientId` / `clientSecret`
  member that is neither a string nor null. Unknown OAuth members are ignored.
- Non-null `disabled` that is not a boolean.
- Non-null `args` that is not an array, or an element that is neither a string nor null.
- Non-null `command`, `url`, `serverUrl` or `cwd` that is not a string.
- Non-null `disabledTools` that is not an array of strings or null elements.
- An empty `command` with no `serverUrl` or `url`. The server loads, but has
  no command to start.
- `authProviderType` with any value but the string `google_credentials` —
  another string, a number, an array or an object alike. The proto enum's
  `MCP_AUTH_PROVIDER_TYPE_GOOGLE_CREDENTIALS` spelling drops the server;
  only the lowercase JSON alias parses.

Server field names match without regard to case: `Command`, `serverURL`
and `DisabledTools` use the same types as their canonical spellings.
OAuth's `clientId` and `clientSecret` also match this way. The top-level
`mcpServers` wrapper, server names, and environment/header member names
remain case-sensitive. Command and credential scans read the same normalized
view, even when this shape rule is disabled.

## What is not reported

- **A server with no connection field.** `serverUrl` wins over `command`
  when both are present, `url` with an optional `type` is a third accepted
  shape, and a server carrying none of them loads without any complaint from
  `agy`.
- **Unknown keys on a server.** They are tolerated.
- **`enabled`.** It is not a key Antigravity reads; `disabled` is the
  toggle. A server written with `"enabled": false` loads, which is worth
  knowing but is not a defect in the file's shape.
- **`timeout`.** It appears in no measured or documented property list for
  this host.
- **A `type` that is not a string.** Measured: unlike every other scalar
  field on a server, a mistyped `type` is tolerated and the server loads.
- **Valid repeated keys.** A repeated `mcpServers` wrapper or server name
  replaces its earlier value. Within a server, fields apply in encounter
  order, including different capitalization of the same field. Repeated
  `env`, `headers` and `oauth` objects merge their members; null clears the
  map. The credential checks read those merged maps too. A type error in
  an earlier field still drops that server, even if a later field replaces
  the bad value; replacing the whole server or wrapper discards it.
- **A null server.** It loads like an empty server object.
- **A finite JSON number outside Python float range in an ignored field.**
  For example, `timeout: 1e400` is valid JSON; literal `Infinity` is not.
- **Null optional fields and null string-collection members.** A null
  `env` value or an `args` or `disabledTools` element is accepted as an
  empty string. A null or empty `serverUrl` is treated as absent, preserving
  a local `command`. A nonempty `serverUrl` takes precedence over `url`.

The warnings above still apply to `authProviderType: ""` (the server is
dropped), `mcpServers: null` (no server map), and `command: ""` without a
URL (no command to start). Accepting a value's type does not make these
configurations useful.

## Examples

**Bad** — an `env` value written as a number, which drops the server and
says nothing:

```json
{
  "mcpServers": {
    "harbour-db": {
      "command": "./bin/harbour-mcp",
      "env": { "PGPORT": 5432 }
    }
  }
}
```

**Good** — a remote server, a local one, and a disabled one:

```json
{
  "mcpServers": {
    "gtfs-feed": {
      "serverUrl": "https://feeds.example/mcp/sse",
      "headers": { "Authorization": "Bearer ${GTFS_FEED_TOKEN}" },
      "disabledTools": ["publish_feed"]
    },
    "harbour-db": {
      "command": "./bin/harbour-mcp",
      "args": ["--read-only"],
      "env": { "PGPORT": "5432" }
    },
    "legacy-planner": {
      "command": "./bin/planner-mcp",
      "disabled": true
    }
  }
}
```

## How to fix

- Wrap the servers in `mcpServers`. Without it Antigravity loads none of
  them.
- Quote every `env` value and every `args` element. `env` is a map and
  `args` an array, but the loader takes strings in both, and a number in
  either drops the server.
- Use `serverUrl` for a remote server, `command` plus `args` for a local
  one. Naming both is allowed; `serverUrl` is what runs.
- Switch a server off with `"disabled": true`.
- Write `authProviderType` as `"google_credentials"`, or leave it out.
- Keep credentials out of the file: reference an environment variable
  (`"${GTFS_FEED_TOKEN}"`) rather than pasting a token into `env`,
  `headers`, `oauth`, or a server's own `clientId` / `clientSecret`.

If Antigravity adds an auth provider newer than this skillsaw release,
allow it in `.skillsaw.yaml`:

```yaml
rules:
  antigravity-mcp-valid:
    extra-auth-provider-types:
      - workspace_credentials
```

An explicit rule `severity` applies to primary file, server and field findings,
including those whose normal failure scope is WARNING. With no override (or
`severity: null`), each failure scope retains its documented default.

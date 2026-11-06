# Skills over MCP

An MCP server can publish Agent Skills through the Skills extension
([SEP-2640](https://modelcontextprotocol.io/seps/2640-skills-extension),
`io.modelcontextprotocol/skills`): each file of a skill becomes a `skill://`
resource, and `skills/list` advertises every skill's frontmatter with a digest
and size for each of its files. The skills themselves are plain Agent Skills, so
in the server's own repository `skillsaw lint` checks them like any other.

To check what a running server actually serves — skills synced from elsewhere,
generated at runtime, or behind a server you consume rather than author — fetch
them and lint the result, for example to catch hidden instructions or other
security problems before an agent loads them:

```bash
skillsaw lint --mcp-server https://mcp.example.com/mcp
skillsaw lint --mcp-server "npx -y @acme/skills-server"     # a stdio server
skillsaw lint --mcp-config .mcp.json --format sarif        # every server in a client config
skillsaw tree --mcp-server URL                             # see what it serves
skillsaw pull --mcp-server URL -o mcp-skills/             # fetch only; lint it later
```

`lint` and `tree` take these options in place of a path; run local paths
separately. The configuration is the one the command would use in the current
directory, so rule settings and severity overrides apply; a baseline does not,
since it describes your repository. The skills are fetched into a temporary
directory that is removed when the run ends, so for report locations that last,
such as SARIF for code scanning, `skillsaw pull` them and lint that directory.

The client speaks both the `2026-07-28` protocol (`server/discover`) and the
earlier `initialize` handshake, over Streamable HTTP or stdio. `--mcp-config`
reads a client config such as `.mcp.json`, `.vscode/mcp.json` or
`.cursor/mcp.json`, with `${VAR}` expansion. A stdio server, named on the
command line or in a config, runs its command, so start only servers you trust.

Treat an MCP config like code: it runs its commands and sends the environment
variables it names to the servers it lists. Never pass `--mcp-config` a config
from a pull request or anywhere else you would not run code from. In CI, lint a
committed `skillsaw pull` directory instead.

## Problems with a server

Some things are wrong with the server, not with any skill, and only fetching can
see them:

- the server cannot be reached or needs authorization;
- a file does not match the digest or size the server advertised, or a
  `SKILL.md` does not match the frontmatter advertised for it — hosts refuse
  such a skill;
- a `skills/list` entry is malformed, for example its name differs from its
  URI or its file list omits `SKILL.md`;
- a skill exceeds the 512 files or 16 MiB that every host must accept;
- a file could not be read or stored, or a limit stopped the fetch early.

These are listed after the lint report, and any of them fails the run;
`skillsaw pull` lists them too and exits 1, but keeps what it fetched.

A server that serves no skills, as most servers in a client config do, is not a
problem: there is just nothing to lint. A config entry skillsaw cannot fetch
from, such as one on the retired HTTP+SSE transport, is skipped with a note.

A skill served as `"dynamic"` has no digests to check; its files are found through
directory reads and linted like the rest.

The fetch acts like an inspector, not a host. It reads each listed file once,
refuses URIs that would land outside the output directory, executes nothing it
fetched, and keeps bytes that fail verification so they are still linted. It is
bounded per server: `--mcp-max-skills` caps the skills listed, `--mcp-max-bytes`
caps every response read (listing pages, directory reads and files), and
`--mcp-timeout` caps each request. When the server answers HTTP 429 or 503, the
fetch retries within that timeout.

## Servers behind auth

skillsaw sends credentials it is given; it does not run an OAuth login.

- **A token or API key:** pass it as a header for a single server,
  `--mcp-header "Authorization: Bearer $TOKEN"`, or give each server its
  `headers` in an MCP config, as `"Authorization": "Bearer ${TOKEN}"`. A token
  another tool obtained, by browser or device-code login, works if the server
  accepts it. Other users of a shared machine can read command-line arguments
  in the process list, so there prefer a config's headers.
- **OAuth login:** let a bridge handle the login and serve the server over
  stdio, for example
  `--mcp-server "npx -y mcp-remote https://mcp.example.com/mcp"`, which opens a
  browser the first time.
- **CI:** an interactive login cannot run there. Run `skillsaw pull` where you
  can log in, commit its directory, and lint that in CI like any other.

Credentials stay out of the snapshot: it records the server's scheme, host and
port, but no path (some services carry a key there), headers, query string or
user info. Redirects are refused, so a server cannot forward your header to
another host.

## Pulling skills

`skillsaw pull -o DIR` fetches without linting and writes a plain skills tree,
`<server>/<skill-path>/SKILL.md` and its files, plus `mcp-skills-snapshot.json`,
which records each server's `skills/list` entries and the problems the fetch
met. A stdio server's directory is named for what its command starts
(`npx -y @acme/skills-server` becomes `skills-server`), an HTTP server's for its
host, and a configured server's for its name in the config. Pulling again
replaces an earlier snapshot, but never a directory holding anything else.

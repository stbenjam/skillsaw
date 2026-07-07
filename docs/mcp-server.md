# MCP Server

`skillsaw mcp` runs a [Model Context Protocol](https://modelcontextprotocol.io)
server over stdio, so coding agents (Claude Code, Cursor, Codex CLI, Gemini
CLI, ...) can lint, grade, and fix the skills, plugins, and instruction files
they are authoring — without shelling out to the CLI.

## Installation

The MCP SDK is an optional extra (it requires Python 3.10+):

```bash
pip install 'skillsaw[mcp]'
```

Without the extra installed, `skillsaw mcp` prints an install hint and exits
non-zero.

## Connecting a client

### Claude Code

```bash
claude mcp add skillsaw -- skillsaw mcp
```

Or without installing anything, via uvx:

```bash
claude mcp add skillsaw -- uvx --from 'skillsaw[mcp]' skillsaw mcp
```

### Cursor / Codex CLI / Gemini CLI

Any MCP client that supports stdio servers works. The generic configuration
is:

```json
{
  "mcpServers": {
    "skillsaw": {
      "command": "skillsaw",
      "args": ["mcp"]
    }
  }
}
```

## Tools

All tools are deterministic and offline. Everything is read-only except
`fix` with `dry_run=false`.

| Tool | Arguments | Returns |
|------|-----------|---------|
| `lint` | `path`, optional `rules` (rule-id filter), optional `strict` | Violations (rule id, severity, message, file, line, docs URL), summary counts, letter grade, and a `passed` verdict. Respects `.skillsaw.yaml` and the baseline file, exactly like `skillsaw lint`. |
| `grade` | `path` | Letter grade (A+ through F), weighted violation density, and estimated content token count — the same scale as the [badge](https://skillsaw.org/cli/#skillsaw-badge). Ignores any baseline. |
| `explain_rule` | `rule_id` | The long-form markdown documentation `skillsaw explain` prints: what the rule checks, why, examples, and configuration options. Unknown ids error with close-match suggestions. |
| `list_rules` | — | Every rule (builtin and installed plugins) with its one-line description, default severity, and autofix support. |
| `fix` | `path`, `dry_run` (default `true`), `suggest` (default `false`) | Applies (or previews) skillsaw's deterministic autofixes and returns a per-file summary. `suggest=true` also applies suggest-confidence fixes, like `skillsaw fix --suggest`. |

A typical agent loop: `lint` the directory being authored, `explain_rule`
anything unclear, `fix` with the default dry run to preview, then `fix` with
`dry_run=false` to apply, and `lint` again to confirm.

## Security

The server never executes content from the repository it lints:

- Custom rules defined in the linted repository's `.skillsaw.yaml` are
  **never loaded** (equivalent to `--no-custom-rules`).
- No tool performs network access; results are computed locally from the
  files on disk.
- Only `fix` with `dry_run=false` writes to the repository, and it only
  applies skillsaw's deterministic autofixes.

Rule plugins installed as Python packages in skillsaw's own environment
(`skillsaw.plugins` entry points) still load normally — they are part of
your toolchain, not of the repository under lint.

## Registry manifest

The repository ships a [`server.json`](https://github.com/stbenjam/skillsaw/blob/main/server.json)
manifest following the [MCP registry schema](https://github.com/modelcontextprotocol/registry),
describing the server as the PyPI package `skillsaw` with the `mcp` extra,
run via `uvx --from 'skillsaw[mcp]' skillsaw mcp`.

# Porting to Agent Plugins

`skillsaw port` converts Claude Code and Codex plugins to
[Agent Plugins v1](https://agent-plugins.org) — the vendor-neutral
plugin format — in place:

```bash
skillsaw port --to agent-plugin .
```

Point it at a single plugin, a marketplace, or any repository: every
discovered plugin is converted. The port is **additive** — it writes a
root `plugin.json` (and, when the plugin has a Claude `.mcp.json`, a
portable `mcp.json`) and never modifies or removes the source format's
files. Both formats coexist in the same directory, so Claude Code and
Codex keep working exactly as before while any Agent Plugins client can
now install the package.

```text
$ skillsaw port --to agent-plugin .
✓ [plugins/release-notes] claude → plugin.json
✓ [plugins/release-notes] claude → mcp.json
  note: commands/ stay as client-specific content — Agent Plugins v1
        defines only skills and MCP servers
✓ [plugins/issue-triage] codex → plugin.json

Ported 2 packages; Agent Plugins validation passed.
```

## What gets translated

- **Manifest metadata** — `name`, `version`, `description`, `author`,
  `homepage`, `repository`, `license`, and `keywords` carry over. A name
  that violates the Agent Plugins name rules (uppercase, underscores) is
  normalized, with a note. Dual-manifest plugins merge both sources,
  Claude values first.
- **MCP configuration** — `.mcp.json` servers become portable `mcp.json`
  entries: Claude's `http` transport maps to `streamable-http`,
  `${CLAUDE_PLUGIN_ROOT}` becomes `${PLUGIN_ROOT}` (or a `./` relative
  `command`), and servers the portable format cannot express (`ws`
  transport, shell-style commands, reserved environment names) are
  skipped with a note rather than silently dropped or mistranslated.
- **Skills** — nothing to do: `skills/*/SKILL.md` is already the Agent
  Plugins location.
- **Commands, agents, hooks** — stay behind as client-specific content;
  Agent Plugins v1 defines only skills and MCP servers.

Every port ends with the Agent Plugins rules
(`agent-plugin-json-valid`, `agent-plugin-mcp-valid`) run over the
output; the command fails if its own output doesn't validate. Use
`--dry-run` to see the exact files before anything is written. A rerun
over an already-ported tree is a no-op, and a root `plugin.json` that
belongs to something else is never overwritten.

## Marketplace catalogs

Agent Plugins v1 defines a package, not a marketplace — clients that
discover plugins through a catalog need one alongside the ported
packages. By default a multi-plugin port also writes Codex's
`.agents/plugins/marketplace.json`, listing every ported plugin as a
`local` source with the spec-recommended policy fields (and the
category carried over from a Claude marketplace entry when one exists).
Codex writing its catalog into the client-neutral `.agents/` directory
reads as a step toward a vendor-neutral catalog format, which makes it
the reasonable one to emit until a real standard exists.
An existing catalog is left untouched —
`codex-marketplace-registration`'s fix can append missing entries.
Control it with `--marketplaces` (default `codex`, `none` to skip);
more catalog formats can be added as marketplaces evolve.

## Keeping it true: `agent-plugin-required`

The opt-in [`agent-plugin-required`](rules/agent-plugin-required.md)
rule turns the one-time conversion into a standing guarantee. Enable it
in `.skillsaw.yaml`:

```yaml
rules:
  agent-plugin-required:
    enabled: true
    severity: error
```

It reports any plugin missing the portable manifest (fixable —
`skillsaw fix` runs the same conversion), shared metadata
that has drifted between the manifests, and a Claude MCP configuration
with no portable counterpart. In CI, that means no plugin merges
without the vendor-neutral format.

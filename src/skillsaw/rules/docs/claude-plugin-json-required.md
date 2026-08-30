## Why

A Claude plugin must have a `.claude-plugin/plugin.json` manifest so
the host application can discover its metadata, commands, and
capabilities. Without this file the plugin directory is just a
collection of unregistered files. The requirement is scoped to
directories with Claude provenance — see "Codex plugins" below before
adding a manifest to a directory another ecosystem owns.

## Examples

**Bad:**

```
my-plugin/
  .claude-plugin/
    commands/
      deploy.md
```

**Good:**

```
my-plugin/
  .claude-plugin/
    plugin.json
    commands/
      deploy.md
```

## How to fix

Create a `.claude-plugin/plugin.json` file with the required fields
(`name`, `description`, `version`). Put commands, agents, skills, and other
plugin content beside the `.claude-plugin/` directory.

## Codex plugins

A directory that carries a `.codex-plugin/plugin.json` manifest is an
OpenAI Codex plugin, and this rule stands down on it — it has a
manifest, just not a Claude one, and `codex-plugin-json-valid`
validates it instead. The exemption is withdrawn when
`.codex-plugin/plugin.json` resolves outside the plugin directory
(discovery rejects it, so no Codex rule covers the directory either),
when a Claude marketplace lists the directory, or when the directory also
carries a Claude `.claude-plugin/` directory whose manifest is missing.

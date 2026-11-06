## Why

A Claude plugin directory that no marketplace entry registers needs a
`.claude-plugin/plugin.json` manifest to name it and carry its metadata;
`claude plugin validate` rejects such a directory with "No manifest found".
The requirement is scoped to directories with Claude provenance.

A directory that a local entry in `.claude-plugin/marketplace.json`
registers is exempt, whatever its `strict` value: Claude Code uses the
entry as the manifest when the plugin has no `plugin.json`.

A `.claude-plugin/marketplace.json` catalog alone does not declare its
parent directory a Claude plugin. A root Codex plugin may host that catalog
without needing a Claude manifest. An actual Claude manifest, an empty
`.claude-plugin/` marker, or an explicit local entry in the Claude catalog
still declares a Claude plugin.

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

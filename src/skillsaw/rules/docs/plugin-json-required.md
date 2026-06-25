## Why

A plugin must have a `.claude-plugin/plugin.json` manifest so the
host application can discover its metadata, commands, and
capabilities. Without this file the plugin directory is just a
collection of unregistered files.

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
(`name`, `description`, `version`). Use `skillsaw add plugin` to
scaffold a new plugin with the correct structure.

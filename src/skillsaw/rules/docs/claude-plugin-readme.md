## Why

A README.md in the plugin directory provides human-readable
documentation for users browsing the repository or marketplace.
Without it, users must read the plugin.json and command files to
understand what the plugin does.

## Examples

**Bad:**

```
my-plugin/
  .claude-plugin/
    plugin.json
```

**Good:**

```
my-plugin/
  README.md
  .claude-plugin/
    plugin.json
```

## How to fix

Create a `README.md` file in the plugin's root directory explaining
what the plugin does, how to install it, and how to use its commands.

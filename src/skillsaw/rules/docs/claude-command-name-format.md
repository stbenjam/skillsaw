## Why

The Name section in a command file tells users and tools the command's
fully qualified identifier. It must follow the `plugin-name:command-name`
format so the runtime can route invocations correctly.

## Examples

**Bad (in plugin `my-plugin`, file `deploy.md`):**

```markdown
## Name

deploy
```

**Good:**

```markdown
## Name

my-plugin:deploy
```

## How to fix

Update the Name section to include the plugin name prefix followed by
a colon and the command name: `plugin-name:command-name`.

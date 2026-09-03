## Why

Plugin names appear in command identifiers (`plugin:command`) and
configuration files. A name that uses uppercase, underscores, or
spaces breaks conventions and may cause lookup failures in
case-sensitive systems.

## Examples

**Bad:**

```json
{"name": "My_Plugin"}
```

**Good:**

```json
{"name": "my-plugin"}
```

## How to fix

Rename the plugin to use kebab-case in `plugin.json` and rename the
plugin directory to match.

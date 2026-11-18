Agent Plugins 1.1.0 defines an optional `hooks.json` at the plugin root.
Enable this draft-format check with `--rule agent-plugin-hooks-valid` or in
the repository configuration. It checks the file against the locally bundled
[1.1.0 working draft](https://github.com/agentplugins/agent-plugins-spec/blob/6395e8906b30e2f333b792bfaa981d790993d56f/spec/1.1.0.md#73-hooks).

## What is checked

- The file resolves to a regular file inside the package. Its JSON object
  contains the canonical 1.1.0 hooks schema identifier and a `hooks` object.
- Each event is one of `SessionStart`, `UserPromptSubmit`, `PreToolUse`,
  `PostToolUse`, and `Stop`. Every declared event has a nonempty handler array.
  An empty `hooks` object is valid.
- Each handler has an executable `command`, optional string-array `args`, and
  optional client extension objects. A command beginning with `./` resolves
  inside the plugin root. Bare commands may refer to programs provided by the
  runtime environment.

A malformed document disables the hooks component. A malformed event or
handler is reported independently so authors can repair the affected entry.
The shared hook inspection rules also see portable commands and arguments.

## How to fix

Declare the same specification version in the plugin manifest and hooks file.
Keep the command and its arguments in separate fields.

```json
{
  "$schema": "https://agent-plugins.org/schemas/1.1.0/hooks.schema.json",
  "hooks": {
    "SessionStart": [{"command": "./hooks/load-context", "args": ["--summary"]}]
  }
}
```

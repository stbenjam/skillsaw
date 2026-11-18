Agent Plugins 1.1.0 defines an optional `hooks.json` at the plugin root.
Enable this draft-format check with `--rule agent-plugin-hooks-valid` or in
the repository configuration. It checks the file against the locally bundled
[1.1.0 working draft](https://github.com/agentplugins/agent-plugins-spec/blob/6395e8906b30e2f333b792bfaa981d790993d56f/spec/1.1.0.md#73-hooks).
The file is inspected only when `plugin.json` declares the 1.1.0 manifest
schema; a 1.0.0 package's `hooks.json` is not part of that format and is
ignored.

## What is checked

- The file resolves to a regular file inside the package. Its JSON object
  contains the canonical 1.1.0 hooks schema identifier and a `hooks` object.
- Each event is one of `SessionStart`, `UserPromptSubmit`, `PreToolUse`,
  `PostToolUse`, and `Stop`. Every declared event has a nonempty handler array.
  An empty `hooks` object is valid.
- Each handler has a `command` that names one executable, optional
  string-array `args`, and an optional `extensions` object; no other handler
  keys are allowed. A command beginning with `./` must resolve inside the
  plugin root. Bare commands may refer to programs provided by the runtime
  environment.

A malformed document makes clients ignore the whole hooks component, so it
is reported once and its events are not inspected. A malformed event or
handler is reported on its own, so authors can repair just that entry.
`hooks-dangerous` and `hooks-prohibited` also inspect portable commands and
arguments.

## How to fix

Declare the 1.1.0 schema in both `plugin.json` and `hooks.json`.
Keep the command and its arguments in separate fields.

```json
{
  "$schema": "https://agent-plugins.org/schemas/1.1.0/hooks.schema.json",
  "hooks": {
    "SessionStart": [{"command": "./hooks/load-context", "args": ["--summary"]}]
  }
}
```

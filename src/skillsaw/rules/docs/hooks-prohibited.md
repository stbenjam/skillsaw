## Why

In security-conscious environments, maintaining an inventory of all active hooks
gives teams full visibility and confidence over what runs during agent sessions.
This rule lets you maintain an explicit allowlist of approved hooks across your
project.

It scans hook configurations defined across supported tools and formats: plugin
`hooks/hooks.json` (Claude and Codex, including Codex manifest-declared and inline
hooks), APM's compiled files, `.claude/settings*.json`, **skill and agent
frontmatter** (`hooks:` key), `<repo>/.codex/hooks.json`, `.muse/hooks.json`, and
Cursor's `.cursor/hooks.json`.

In addition to traditional command hooks that spawn shell processes, this inventory
also tracks non-process action handlers — such as `http` endpoints, `mcp_tool`
invocations, `prompt` templates, and `agent` workflows. Tracking these handlers
ensures team reviewers can inspect and approve all automated behaviors declared
in the repository.

Prompt handlers are identified by their text (`prompt:<text>`), using a consistent
format across both Claude Code's nested structure and Cursor's
`.cursor/hooks.json`, making it easy to share allowlist entries across hosts.

## Examples

**Needs review (no allowlist configured):**

```json
{
  "hooks": {
    "PostToolUse": [
      {"hooks": [{"type": "command", "command": "scripts/format.sh"}]}
    ]
  }
}
```

**Approved (with allowlist):**

```yaml
# .skillsaw.yml
rules:
  hooks-prohibited:
    allowlist:
      - "scripts/format.sh"
```

## How to fix

Review the flagged hook and, once verified as safe, add it to the `allowlist` in
your skillsaw configuration. Entries match the identifier shown in the finding
message exactly. This rule is disabled by default — enable it whenever your
project requires strict supply-chain policy enforcement.

For standard `command` hooks, use the command string itself. For exec-form hooks,
arguments are joined with spaces (`command arg1 arg2`). Note that allowlisting
only the base executable does not permit arbitrary arguments passed to it.

For handlers that invoke actions without running a shell command, the allowlist
uses a descriptive identity based on what the handler triggers:

| Handler `type` | Allowlist entry |
| --- | --- |
| `mcp_tool` | `mcp_tool:<server>/<tool>` |
| `http` | `http:<url>` |
| `prompt` | `prompt:<prompt>` |
| `agent` | `agent:<prompt>` |

If a handler is missing these identifying fields, it falls back to its bare type
(such as `http`). Rather than allowlisting an empty handler, update the handler
configuration with its required target so it can be properly validated.

```yaml
# .skillsaw.yml
rules:
  hooks-prohibited:
    allowlist:
      - "scripts/format.sh"
      - "mcp_tool:linter/format"
      - "http:https://ci.example.com/hooks/post-tool-use"
```


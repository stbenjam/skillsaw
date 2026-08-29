## Why

GitHub Copilot and VS Code both load custom agents from
`.github/agents/**/*.md`, but they do not consume exactly the same
frontmatter. GitHub cloud supports agent-scoped MCP servers and metadata;
VS Code adds prioritized model lists, subagents, handoffs, and preview hooks.
A syntactically valid field written in the wrong dialect is silently ignored,
which leaves a shared agent only partly configured.

This rule validates the common scalar fields, real YAML booleans, tool and
model collections, subagent/tool coordination, metadata, handoffs, hook
shape, the two documented `target` values, and GitHub's 30,000-character
prompt limit. In an `*.agent.md` file, omitted `target` means both
environments and accepts the documented union. Other Markdown files under
`.github/agents/` are VS Code-only, as are legacy chatmodes. Unknown tool
names remain valid because both consumers ignore tools they do not provide.

Embedded `mcp-servers` configurations in cloud or shared `*.agent.md` files
are scanned by the shared [`mcp-valid-json`](mcp-valid-json.md) and
[`mcp-prohibited`](mcp-prohibited.md) rules. Lifecycle hooks in VS Code-capable
agent files are scanned by [`hooks-dangerous`](hooks-dangerous.md). GitHub
template variables (`${{ secrets.NAME }}` and `${{ vars.NAME }}`) are recognized
as valid placeholders.


Legacy `.github/chatmodes/**/*.chatmode.md` files and non-`*.agent.md` files under
`.github/agents/` are also validated under VS Code conventions to assist migration.


## Severity

Malformed YAML, wrong field types, invalid targets, unusable collections,
invalid handoffs or hook structures, missing agent-tool access, and an
oversized cloud prompt are errors.

Compatibility findings are warnings because the file remains usable in its
selected environment: VS Code-only fields on `target: github-copilot`, cloud
MCP/metadata on `target: vscode`, a cloud-only tools string in VS Code, and a
VS Code model array in cloud. The retired `infer` field is also a warning;
`disable-model-invocation` takes precedence when both are present.

Unknown top-level fields are accepted by default because the format evolves
quickly. Set `report-unknown-fields: true` to surface them as warnings.

## Examples

**Bad** — the target and types are not recognized, and the subagent cannot be
invoked through the restricted tools list:

```markdown
---
description: Reviews a proposed change
target: github
tools: [read, 42]
agents: [Researcher]
disable-model-invocation: "false"
---

Review the requested changes.
```

**Good for VS Code** — the agent tool enables the listed subagents and the
handoff uses a qualified model:

```markdown
---
description: Plans a change and hands approved work to implementation
target: vscode
tools: [read, search, agent]
agents: [Researcher, Implementer]
model: [Claude Sonnet 4.5, GPT-5.2]
handoffs:
  - label: Start Implementation
    agent: Implementer
    send: false
    model: GPT-5.2 (copilot)
---

Create a detailed implementation plan.
```

## How to fix

- Use `target: vscode`, `target: github-copilot`, or omit `target` for a
  shared agent.
- Keep VS Code `tools` as a YAML list. Add `agent`, `custom-agent`, or `Task`
  when a non-empty `agents` list is paired with an explicit tools restriction.
- Replace quoted booleans with `true` or `false`; replace retired `infer` with
  `user-invocable` and `disable-model-invocation`.
- Keep handoff `label`, `agent`, optional `prompt`, and optional qualified
  `model` values as non-empty strings; keep `send` as a boolean.
- Move a field to the environment that consumes it, or remove the explicit
  target when the file is intentionally shared.

To warn on preview keys this release does not recognize:

```yaml
rules:
  copilot-agent-valid:
    report-unknown-fields: true
```

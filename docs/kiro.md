# Kiro repository resources

skillsaw discovers Kiro resources at the repository root and in nested project
folders, such as `packages/api/.kiro/`. It lints each authored file once; it does
not simulate which instructions a running session has selected.

| Location relative to each project | Attached content |
|---|---|
| `.kiro/steering/**/*.md` | Markdown body, with YAML metadata kept separate |
| `.kiro/agents/**/*.json` | Agent configuration, inline `prompt` prose, and inline `mcpServers` |
| `.kiro/agents/**/*.md` | Agent frontmatter, Markdown system-prompt body, and inline `mcpServers` |
| `.kiro/settings/mcp.json` | Workspace MCP configuration |
| `.kiro/skills/**/SKILL.md` | Portable Agent Skills, including nested project folders |

A JSON agent's literal relative `file://` prompt is resolved from the agent
file's directory. Contained prompt files receive the shared content and Markdown
link checks. If the same file is already steering, a skill, or another instruction
file, it keeps its existing content block. Inline JSON prompts are diagnostic-only:
the decoded string has no editable Markdown span or reliable JSON line number.
Their size is not charged to the whole-file context budget, which would otherwise
count configuration as instruction text.

Agent descriptions and steering with `inclusion: auto` receive the shared
`content-description-routing` advice. Normal Markdown links use the shared
`content-broken-internal-reference` rule and resolve beside the prose file.

## Enable structural checks

These new rules are opt-in pending a ten-repository accuracy survey:

```yaml
rules:
  kiro-agent-valid:
    enabled: true
  kiro-mcp-valid:
    enabled: true
  kiro-references:
    enabled: true
```

- `kiro-agent-valid` checks JSON/YAML syntax, the agent object's shape, string
  metadata, string-array tool selectors, boolean inclusion flags, and resource
  and MCP containers. It accepts unknown fields and resource objects without
  attempting to validate the entire host schema.
- `kiro-mcp-valid` checks the server map and the documented types of `command`,
  `url`, `args`, `env`, `headers`, `disabled`, `autoApprove`, `disabledTools`,
  `oauthScopes`, and the `oauth` container. Partial entries such as
  `{"disabled": true}` and `{"disabledTools": ["delete_item"]}` are accepted.
  It does not require an endpoint on an overlay or infer an active transport.
- `kiro-references` checks literal relative JSON prompt URIs, `file://` resource
  entries, and steering `#[[file:path]]` / `#[[folder:path]]` references. Resource
  and steering paths use the directory containing `.kiro` as the workspace base;
  this assumes the resource is used from that workspace root. A steering line or
  range suffix is stripped for the existence check; line ranges are not validated.
  Code examples are excluded using the Markdown AST.

The shared `mcp-valid-json` credential and URL-userinfo checks and opt-in
`mcp-prohibited` policy apply to workspace and inline agent servers. Kiro's MCP
shape is kept out of Claude-specific validation: Claude reserved names and
transport requirements are not imposed on Kiro. Credential checks include
`env`, `headers`, and `oauth`, and remain active when Kiro structural checks are
disabled. They do not connect to servers or execute commands.

YAML field and Markdown body findings carry source line numbers. JSON findings
are at file level. Rule severities and exclusions use the normal skillsaw config.

## Supported contracts and boundaries

The implementation targets the common JSON subset in the **CLI 2.x reference**
and the JSON/Markdown forms documented for **IDE 1.x / CLI V3**, checked against
the official documentation on **2026-10-11** (the custom-agent page was updated
2026-10-10). Markdown and recursive agent names are current-contract support;
this does not assert that CLI 2.x discovers Markdown or nested agents. Recursive
steering inspection covers the documented `file://.kiro/steering/**/*.md` resource
pattern. It does not claim every steering file enters every session automatically.

CLI 2.x's `allowedTools`, `toolsSettings`, `toolAliases`, and `keyboardShortcut`
are left intact. V3's `permissions` and both versions' hook fields are left
uninterpreted. A missing `permissions` block is not diagnosed: the file could be
an intentionally maintained legacy profile. This is a shared-subset check, not
a V3 migration validator. It does not validate permission effects, capability or
model allowlists, hooks, Powers, or hidden/runtime-injected instructions.

The released historical [agent-v1 schema at amazon-q-developer-cli v1.19.7](https://github.com/aws/amazon-q-developer-cli/blob/cf39ab6297ee7654fcbeed253445d35fe5c92b07/schemas/agent-v1.json)
and its [prompt resolver](https://github.com/aws/amazon-q-developer-cli/blob/cf39ab6297ee7654fcbeed253445d35fe5c92b07/crates/chat-cli/src/cli/agent/mod.rs)
corroborate the legacy nullable fields and agent-relative prompt paths. That
release predates Kiro CLI 2.x and is not presented as a current Kiro schema.
No full historical schema is imposed on current profiles.

Kiro gives workspace agents precedence over same-named global agents. MCP
configuration resolves agent entries ahead of workspace entries and workspace
entries ahead of global entries; `includeMcpJson` also affects what is loaded.
Workspace steering can override global instructions. skillsaw inspects authored
records independently. It does not read `~/.kiro`, cloud sync, per-user trust,
permission files, environment values, or runtime session state to compute the
merged result. Nested `.kiro` directories represent potential workspace roots;
they are not all combined into one simulated workspace.

References outside the repository, absolute paths, home expansion, environment
substitution, resource globs, `skill://` lookup, and knowledge-base loading are
not resolved. A Markdown agent's body is inspected as its system prompt; a
`prompt` frontmatter key is not followed because precedence against the body is
not established here. General resource files are checked for existence but not
attached as prose; their contents can be source code or other non-instruction
data. Steering inclusion modes/patterns and actual activation remain host decisions.

## Official references

- [Custom agents: JSON/Markdown, nested names, and precedence](https://kiro.dev/docs/custom-agents/)
- [Agent configuration reference: current contract and legacy differences](https://kiro.dev/docs/custom-agents/configuration-reference/)
- [CLI 2.x reference](https://kiro.dev/docs/cli/2x-reference/)
- [Sub-agent selection by description](https://kiro.dev/docs/custom-agents/subagents/)
- [Steering: recursive resource glob, inclusion, and references](https://kiro.dev/docs/steering/)
- [MCP configuration and partial overrides](https://kiro.dev/docs/mcp/configuration/)
- [Configuration scopes](https://kiro.dev/docs/configuration/)

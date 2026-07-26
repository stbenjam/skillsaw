# Repository Types

skillsaw automatically detects your repository structure. A repository can match multiple types simultaneously (e.g. an agentskills repo that also has `.coderabbit.yaml`).

## agentskills.io Skills

Standalone skill repositories following the [agentskills.io](https://agentskills.io) specification:

```
my-skill/
├── SKILL.md              # Required: metadata + instructions
├── scripts/              # Optional: executable code
├── references/           # Optional: documentation
├── assets/               # Optional: templates, resources
├── evals/                # Optional: evaluation tests
│   └── evals.json
└── <any-dir>/            # Arbitrary directories allowed per spec
```

Skill collections (multiple skills in subdirectories) are also supported:

```
skills-repo/
├── skill-one/
│   └── SKILL.md
└── skill-two/
    └── SKILL.md
```

Standard discovery paths (`.claude/skills/`, `.github/skills/`, `.agents/skills/`) are checked automatically.

## Single Plugin

```
my-plugin/
├── .claude-plugin/
│   └── plugin.json
├── commands/
│   └── my-command.md
├── skills/
│   └── my-skill/
│       └── SKILL.md
└── README.md
```

## Marketplace (Multiple Plugins)

skillsaw supports multiple marketplace structures per the [Claude Code specification](https://docs.claude.com/en/docs/claude-code/plugin-marketplaces):

### Traditional Structure (plugins/ directory)

```
marketplace/
├── .claude-plugin/
│   └── marketplace.json
└── plugins/
    ├── plugin-one/
    │   ├── .claude-plugin/
    │   └── commands/
    └── plugin-two/
        ├── .claude-plugin/
        └── commands/
```

### Flat Structure (root-level plugin)

```
marketplace/
├── .claude-plugin/
│   └── marketplace.json    # source: "./"
├── commands/
│   └── my-command.md
└── skills/
    └── my-skill/
```

### Custom Paths and Mixed Structures

Plugins from `plugins/`, custom paths, and remote sources can coexist in one marketplace. Only local sources are validated.

## OpenAI Codex Plugin

Directories with a `.codex-plugin/plugin.json` manifest, per the [Codex plugin specification](https://developers.openai.com/plugins/build/plugins):

```text
my-plugin/
├── .codex-plugin/
│   └── plugin.json       # Required — only this file belongs here
├── skills/
│   └── my-skill/
│       └── SKILL.md
├── hooks/
│   └── hooks.json        # Optional
├── .mcp.json             # Optional: bundled MCP servers
├── .app.json             # Optional: registered MCP mappings
└── assets/               # Optional: icons, screenshots
```

skillsaw probes the repository root, `plugins/*`, `.codex/plugins/*`, and every local source the Codex marketplace declares.

`.codex/plugins/*` is where Codex installs plugins into a checkout, so the split there is between what the repository *runs* and what the repository *wrote*:

| Rule | On an installed plugin | Why |
|---|---|---|
| `hooks-dangerous`, `hooks-prohibited`, `hooks-json-valid` | **Runs** | These commands execute in this checkout. Whoever wrote them, they are this checkout's exposure. |
| `mcp-valid-json`, `mcp-prohibited` | **Runs** | Same — the host spawns these commands here. |
| `agentskill-*` | **Runs** | These skills enter the agent's context window here. |
| `codex-plugin-json-valid`, `codex-plugin-structure` | **Stands down** | A kebab-case name, a missing `description` or a dangling asset path is a defect in a file the developer cannot edit. |
| `codex-marketplace-registration` | **Stands down** | The repository did not author the plugin; its published catalog has no business listing it. |

The line is authorship, not discovery: skillsaw does not walk `.claude/plugins/*` at all, so a broken vendor manifest there is likewise not the repository's problem.

`hooks` and `mcpServers` accept a path, an array of paths, or the config inline — all forms are followed, because a hook written inline runs exactly like one in a file. `skills` names directories:

| Field | Default location | Also followed |
|---|---|---|
| `hooks` | `hooks/hooks.json` | declared paths, inline objects |
| `mcpServers` | `.mcp.json` | declared paths, inline server maps |
| `skills` | `skills/` | declared directory paths |

Paths that leave the plugin root are not followed; `codex-plugin-json-valid` reports them.

`skillsaw docs` describes Codex-only plugins as well, reading name, version, description, `interface.displayName`, author and license from the Codex manifest.

## OpenAI Codex Marketplace

Repositories with a Codex catalog at `.agents/plugins/marketplace.json`:

```text
marketplace/
├── .agents/
│   └── plugins/
│       └── marketplace.json
└── plugins/
    ├── plugin-one/
    │   └── .codex-plugin/plugin.json
    └── plugin-two/
        └── .codex-plugin/plugin.json
```

Sibling files in `.agents/plugins/` are read as catalogs too. A name ending in `marketplace.json` at a separator — `api_marketplace.json`, which is how `openai/plugins` splits its catalog — is taken on existence alone, so a broken one still reaches the rule that reports it. Any other `*.json` has to carry a `plugins` array to be treated as a catalog.

Codex also reads `.claude-plugin/marketplace.json` for backward compatibility, but skillsaw leaves that path to the Claude `marketplace-*` rules: the two schemas disagree (Claude requires `owner`; Codex adds `policy`, `category`, and `interface`), so linting one file against both would report contradictory violations. The consequence is that a Codex-schema catalog written to the legacy path *will* be checked against the Claude schema — a missing `owner`, and an unknown `local` source type on every entry. Put a Codex catalog at `.agents/plugins/marketplace.json`.

Both Codex types are independent of the Claude types — a repository commonly ships both manifests, and skillsaw detects both.

## `.claude/` Directory

Repositories with a `.claude/` directory containing commands, skills, hooks, agents, or rules. When APM is present, `.claude/` is treated as compiled output and this type is not detected.

## CodeRabbit

Repositories with a `.coderabbit.yaml` file. skillsaw validates the instruction fragments within the config.

## Promptfoo

Repositories with promptfoo eval configs (`promptfooconfig*.yaml` or YAML files in `evals/` directories). Prompt strings in the config are treated as content blocks, so all `content-*` rules apply to them automatically. Dedicated `promptfoo-*` rules validate config structure, assertion coverage, and metadata.

## APM (Agent Package Manager)

Repositories with an `.apm/` directory or `apm.yml` file. APM manages dependencies and compiles instruction files for all supported agents (`.claude/`, `.cursor/rules/`, `.github/instructions/`, etc.). When APM is present it is the authoritative source — `.claude/` is treated as compiled output.

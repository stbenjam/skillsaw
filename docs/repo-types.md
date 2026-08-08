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
├── evals/                # Optional convention from the evaluation guide
│   └── evals.json
├── agents/
│   └── openai.yaml       # Optional: OpenAI skill metadata (interface, policy, dependencies)
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

Standard discovery paths are checked automatically: `.agents/skills/`,
`.apm/skills/`, `.claude/skills/`, `.github/skills/`, `.cursor/skills/`,
`.clinerules/skills/`, `.cline/skills/` and `.qwen/skills/`. A `SKILL.md`
under any of them makes the repository an Agent Skills repository, which
turns on the `agentskill-*` rules.

## Agent Plugins

Portable plugin packages following the [Agent Plugins v1
specification](https://agent-plugins.org/specification):

```text
my-plugin/
├── plugin.json           # Required: exactly at the plugin root
├── skills/               # Optional
│   └── my-skill/         # Immediate child directory
│       └── SKILL.md      # Agent Skills specification
└── mcp.json              # Optional: portable MCP server configuration
```

Each skill must be an immediate child of `skills/`; deeper descendants are not
discovered as additional skills. `plugin.json` and, when present, `mcp.json`
must use the canonical Agent Plugins v1 schema identifiers. The
`agent-plugin-json-valid` and `agent-plugin-mcp-valid` rules validate those
files, while the `agentskill-*` rules validate discovered `SKILL.md` files.

Automatic detection is deliberately strict. A `plugin.json` at the lint root,
or at an immediate `plugins/*` child, must declare a canonical Agent Plugins
manifest schema identifier. This both supports multi-package collections and
avoids claiming unrelated repositories that happen to contain `plugin.json`.
An `mcp.json` alone is not detection evidence. Supported v1 manifests are
validated locally; a canonical identifier for an unsupported version is still
detected so the version error can be reported.

Use `skillsaw lint --type agent-plugin` to force Agent Plugin validation when
the manifest is missing, malformed, incomplete, or declares the wrong schema;
the defect is then reported instead of preventing detection.

Agent Plugins can coexist with Claude and Codex plugin formats. A repository
may contain root `plugin.json`, `.claude-plugin/plugin.json`, and
`.codex-plugin/plugin.json` markers at the same time; skillsaw detects each
matching repository type and applies its rule family independently. One
format's manifest does not substitute for another's.

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
│       ├── SKILL.md
│       └── agents/
│           └── openai.yaml   # Optional: OpenAI skill metadata
├── agents/
│   └── openai.yaml       # Observed plugin-root metadata form (catalog compatibility)
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
| `hooks-dangerous`, `hooks-prohibited`, `hooks-json-valid` | **Runs (no autofix)** | These commands execute in this checkout. Whoever wrote them, they are this checkout's exposure. |
| `mcp-valid-json`, `mcp-prohibited` | **Runs (no autofix)** | Same — the host spawns these commands here. |
| `agentskill-*` | **Runs (no autofix)** | These skills enter the agent's context window here. |
| `codex-plugin-json-valid`, `codex-plugin-structure` | **Stands down** | A kebab-case name, a missing `description` or a dangling asset path is a defect in a file the developer cannot edit. |
| `codex-openai-metadata` | **Stands down** | Same — a vendor plugin's `agents/openai.yaml` is presentation metadata the developer cannot edit, and it configures nothing that executes here. |
| `codex-marketplace-registration` | **Stands down** | The repository did not author the plugin; its published catalog has no business listing it. |

The line is authorship, not discovery: skillsaw does not walk `.claude/plugins/*` at all, so a broken vendor manifest there is likewise not the repository's problem.
Findings under `.codex/plugins/*` are diagnostic only; autofix never rewrites
vendor-managed installed content.

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

Sibling files in `.agents/plugins/` are read as catalogs too. A name ending in `marketplace.json` at a separator — `api_marketplace.json`, which is how `openai/plugins` splits its catalog — is taken on existence alone, so a broken one still reaches the rule that reports it. Any other `*.json` has to carry a `plugins` array with at least one entry declaring a `source` to be treated as a catalog — a version-pin or metadata sibling with no sources is left alone, which also means a source-less *broken* catalog under an arbitrary name goes unlinted; give a real catalog a `marketplace.json`-suffixed name so existence alone claims it.

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

## Editor and CLI tool files

These are not repository types — skillsaw picks them up in any repository,
whatever its type, because they ship in the checkout. Every **prose** file
listed below gets the full `content-*` rule set (weak language,
contradictions, attention dead zones, secrets, and the rest) plus the
security rules, because its text lands in an agent's context window. The
JSON configuration files — `mcp.json`, `hooks.json` — are machine config,
never linted as prose; they get the MCP and hook rules instead.

Where a tool reads `AGENTS.md`, that is the file skillsaw expects you to write
— Cursor, Copilot, Cline and Codex all read it, and one well-linted AGENTS.md
beats four per-vendor copies that drift apart. skillsaw does not reimplement a
per-vendor instruction format on top of it; what it adds is coverage of the
prose each tool keeps in its own directory, plus structural validation
wherever a tool's own metadata can fail silently — see
[`cursor-rules-valid`](rules/cursor-rules-valid.md) and
[`cursor-hooks-valid`](rules/cursor-hooks-valid.md).

| Tool | Files linted |
| --- | --- |
| **Portable** | `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `QWEN.md`, `.agents/skills/*/SKILL.md` |
| **Cursor** | `.cursor/rules/**/*.mdc`, `.cursor/commands/**/*.md`, `.cursor/skills/*/SKILL.md`, `.cursor/mcp.json`, `.cursor/hooks.json`, legacy `.cursorrules` |
| **Copilot / VS Code** | `.github/copilot-instructions.md`, `**/*.instructions.md`, `.github/prompts/**/*.prompt.md`, `.github/agents/**/*.md`, legacy `.github/chatmodes/**/*.chatmode.md`, `.github/skills/*/SKILL.md`, `.vscode/mcp.json` |
| **Cline** | `.clinerules` (file), `.clinerules/**/*.md`, `.clinerules/**/*.txt` (excluding `workflows/`, `hooks/`, `skills/`), `.clinerules/workflows/**/*.md`, `.clinerules/skills/*/SKILL.md`, `.cline/skills/*/SKILL.md` |
| **Qwen Code** | `QWEN.md`, `.qwen/skills/*/SKILL.md` |
| **Kiro** | `.kiro/steering/*.md` |
| **Windsurf** | `.windsurfrules` |

skillsaw finds `.cursor/`, `.github/` and `.clinerules/` anywhere in the
tree, so a monorepo package that carries its own set is linted alongside the
root's. How much each tool actually reads from a nested directory varies,
and not every case is settled: Cursor documents nested `AGENTS.md` and
`.cursor/skills/`, but steers rules toward a single root `.cursor/rules/`
scoped with `globs`, and reports on whether nested rule directories load
disagree across versions. VS Code walks from the workspace folder up to the
repository root. Cline and `.github/copilot-instructions.md` resolve one
path relative to the workspace directory, so a nested copy is read only when
that directory is the workspace. skillsaw lints all of them either way — a
committed instruction file is worth checking wherever a teammate might open
it, and a rule that turns out not to load is worth knowing about too.

MCP configuration is read for its servers wherever it lives, so
`mcp-valid-json` and `mcp-prohibited` cover `.cursor/mcp.json` and
`.vscode/mcp.json` as well as `.mcp.json`. VS Code spells the server map
`servers` and adds a sibling `inputs` array for prompted variables; skillsaw
reads the former and ignores the latter.

Files that are on-demand rather than always-on — Cursor commands, Copilot
prompt files, Cline workflows — are budgeted by
[`context-budget`](rules/context-budget.md) as commands, not as instruction
files, because they enter the context window only when invoked.

`.cursor/hooks.json` is a command-execution surface that ships in the
repository, so its commands are scanned by
[`hooks-dangerous`](rules/hooks-dangerous.md) and
[`hooks-prohibited`](rules/hooks-prohibited.md) alongside Claude Code hooks
and settings. Cursor's schema is flatter than Claude's — hooks hang directly
off the event name rather than off a matcher group — so `hooks-json-valid`
leaves the file alone and `cursor-hooks-valid` validates the shape instead.
A `type: "prompt"` hook injects text rather than spawning a process, so the
command scanners skip it — but Cursor puts that text into the agent's
context every time the event fires, which makes it shipped instruction
prose. Its `prompt` string is linted as content, so
[`security-hidden-instructions`](rules/security-hidden-instructions.md) and
the other injection scanners read it, and `hooks-prohibited` counts it as a
hook. JSON carries no line numbers, so those findings name the file without
a line.

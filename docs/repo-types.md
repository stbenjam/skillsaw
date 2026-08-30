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
`.clinerules/skills/`, `.cline/skills/`, `.qwen/skills/`,
`.opencode/skills/` and `.opencode/skill/`. A portable `SKILL.md` under any
of them makes the repository an Agent Skills repository, which turns on the
`agentskill-*` rules.

Devin also reads native skills from `.devin/skills/`, including that directory
under nested workspace/package roots. Those files deliberately use a separate
dialect: their YAML frontmatter is optional, `name` defaults from the
directory, and Devin adds model, subagent, permission, tool, and trigger
fields. They get the shared content and security rules plus
[`devin-skill-valid`](rules/devin-skill-valid.md), not the portable
`agentskill-valid`/`agentskill-name` requirements.

Windsurf skills under `.windsurf/skills/` follow the portable Agent Skills
dialect: `name` and `description` are required, and the specification expresses
`allowed-tools` as a space-separated string. Skillsaw also accepts the
historical list form for compatibility. Like Devin skills, nested Windsurf
skill collections are discovered. A skill under `.agents/skills/` also remains
a portable Agent Skill even when the repository contains Devin configuration.

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

## MCP Registry publisher metadata

Publisher repositories for the
[official MCP Registry](https://github.com/modelcontextprotocol/registry)
can keep one or more `server.json` documents at the repository root or inside
monorepo packages:

```text
weather-server/
├── server.json           # Registry publisher metadata
└── package.json          # npm ownership metadata, when locally available
```

Automatic detection requires either the canonical MCP Registry `$schema` URL
or the Registry's distinctive server identity plus package/remote shape. This
keeps unrelated application files named `server.json` out of scope. Use
`--type mcp-registry` when an intended Registry document is too malformed to
provide detection evidence.

The Registry rules validate strict JSON against the released schema each
document declares, enforce the reverse-DNS server namespace and current
transport/registry type vocabulary, reject version ranges, recommend strict
Semantic Versioning, and compare a local npm package's `mcpName` with the
`server.json` `name`. The npm check never queries a package registry; an
external package with no matching local `package.json` is left alone.

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

Repositories with an `.apm/` directory or `apm.yml` file. APM manages dependencies and compiles instruction files for all supported agents (`.claude/`, `.cursor/rules/`, `.github/instructions/`, etc.). When APM is present it is the authoritative source — `.claude/` is treated as compiled output. Package content under `apm_modules/` is externally sourced: it is linted but never autofixed by default, and `lint-external-content: false` omits it from the lint tree.

## Editor and CLI tool files

These are not repository types — skillsaw picks them up in any repository,
whatever its type, because they ship in the checkout. Every **prose** file
listed below gets the `content-*` rules that apply to it (weak language,
contradictions, attention dead zones, secrets, and the rest) plus the
security rules, because its text lands in an agent's context window. A few
content rules are scoped to a role rather than to all prose —
`content-instruction-drift` compares always-on instruction files, so it
does not look at on-demand commands, prompts, agents or workflows. The JSON
configuration files — `mcp.json`, `hooks.json` — are machine config, never
linted as prose; they get the MCP and hook rules instead.

The same separation applies to the Vercel skills CLI's project
`skills-lock.json`: it is generated machine state, so only
[`skills-lock-valid`](rules/skills-lock-valid.md) checks it. The rule validates
the structure and portability metadata the CLI reads; it does not pass the
generated JSON through content-quality rules. Installed skill directories
named by remote lock entries are tagged as externally sourced. They remain
visible to rules by default but are never autofixed; see
[`lint-external-content`](configuration.md#external-content) for the opt-out.

Where a tool reads `AGENTS.md`, that is the file skillsaw expects you to write
— Cursor, Copilot, Cline, OpenCode and Codex all read it, and one well-linted
AGENTS.md beats five per-vendor copies that drift apart. skillsaw does not
reimplement a per-vendor instruction format on top of it; what it adds is
coverage of the prose each tool keeps in its own directory, plus structural
validation wherever a tool's own metadata can fail silently — see
[`cursor-rules-valid`](rules/cursor-rules-valid.md),
[`cursor-hooks-valid`](rules/cursor-hooks-valid.md),
[`copilot-agent-valid`](rules/copilot-agent-valid.md), and
[`opencode-config-valid`](rules/opencode-config-valid.md).

| Tool | Files linted |
| --- | --- |
| **Portable** | `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `QWEN.md`, `.agents/skills/*/SKILL.md` |
| **Vercel skills CLI** | Every `skills-lock.json`, plus matching installed skill payloads unless `lint-external-content: false` |
| **Cursor** | `.cursor/rules/**/*.mdc`, `.cursor/commands/**/*.md`, `.cursor/skills/*/SKILL.md`, `.cursor/mcp.json`, `.cursor/hooks.json`, legacy `.cursorrules` |
| **Copilot / VS Code** | `.github/copilot-instructions.md`, `**/*.instructions.md`, `.github/prompts/**/*.prompt.md`, `.github/agents/**/*.md`, legacy `.github/chatmodes/**/*.chatmode.md`, `.github/skills/*/SKILL.md`, `.vscode/mcp.json` |
| **Cline** | `.clinerules` (file), `.clinerules/**/*.md`, `.clinerules/**/*.txt` (excluding `workflows/`, `hooks/`, `skills/`), `.clinerules/workflows/**/*.md`, `.clinerules/skills/*/SKILL.md`, `.cline/skills/*/SKILL.md` |
| **OpenCode** | `opencode.json` or `opencode.jsonc` at the root and in `.opencode/`, `.opencode/commands/**/*.md`, `.opencode/agents/**/*.md`, `.opencode/modes/*.md`, `.opencode/skills/*/SKILL.md`, and the 1.x singular spelling of each (`command/`, `agent/`, `mode/`, `skill/`). Repository-local files matched by `instructions` paths or globs are also linted; remote URLs are not fetched. |
| **Devin CLI / Desktop** | `.devin/rules/**/*.md`, `.devin/global_rules.md`, `.devin/skills/*/SKILL.md`, nested `AGENTS.md`/`agents.md`, `AGENTS.local.md`, `AGENT.md`, `CLAUDE.md`; legacy `.windsurf/rules/`, `.windsurf/global_rules.md`, and `.windsurfrules` |
| **Windsurf** | `.windsurf/skills/*/SKILL.md` (portable Agent Skills dialect, including nested workspace roots) |
| **Qwen Code** | `QWEN.md`, `.qwen/skills/*/SKILL.md` |
| **Kiro** | `.kiro/steering/*.md` |

Discovery and validation are separate layers for Copilot. Every Markdown file
under `.github/agents/` and every `*.chatmode.md` file under the legacy
`.github/chatmodes/` directory is attached as agent prose, so it receives the
shared content and security rules.
[`copilot-agent-valid`](rules/copilot-agent-valid.md) additionally validates
the YAML fields that determine how GitHub cloud and VS Code interpret the
agent, including their target-specific model, tool, subagent, handoff, MCP,
metadata, and hook behavior. Unknown tool names remain valid, matching both
consumers' forward-compatible behavior.

skillsaw finds `.cursor/`, `.github/`, `.clinerules/`, `.opencode/`, `.devin/`
and `.windsurf/`
anywhere in the tree, so a monorepo package that carries its own set is
linted alongside the root's. How much each tool actually reads from a nested
directory varies, and not every case is settled: Cursor documents nested
`AGENTS.md` and `.cursor/skills/`, but steers rules toward a single root
`.cursor/rules/` scoped with `globs`, and reports on whether nested rule
directories load disagree across versions. VS Code walks from the workspace
folder up to the repository root. Cline and
`.github/copilot-instructions.md` resolve one path relative to the workspace
directory, so a nested copy is read only when that directory is the
workspace. OpenCode walks from the working directory up to the git worktree
root and merges every `.opencode/` it passes, so a nested one is read as
well as the root's. Devin reads rule directories and its supported plain
instruction files at multiple project levels; Devin Desktop also discovers
`AGENTS.md` case-insensitively. skillsaw lints every nested tool directory either way —
committed instructions are worth checking wherever a teammate might open
them, and a rule that turns out not to load is worth knowing about too.

`skills-lock.json` is recursive for a different reason: each project that
runs the skills CLI owns its own lockfile, so a monorepo can legitimately
commit several. Exact-name lockfiles are discovered throughout the checkout;
vendored directories and configured `exclude` paths stay out of scope.
Lockfiles still contribute external-source provenance when the lockfile path
itself is excluded: an `exclude` must not make autofix reinterpret a managed
dependency as authored content.

The plain `GEMINI.md` and `QWEN.md` formats remain root-only. `AGENTS.md`
(including Desktop's case-insensitive spelling), `AGENTS.local.md`,
`AGENT.md`, `CLAUDE.md`, and `.windsurfrules` are discovered at every project
level for Devin's location-scoped behavior. A file shared with another tool
is attached once, so a nested `CLAUDE.md` or `AGENTS.md` does not produce
duplicate content findings.

Most conventional skill directories remain root-only: a skill in
`apps/web/.cursor/skills/review/SKILL.md` is not discovered. Devin and
Windsurf are the exceptions because the workspace scan explicitly supports
nested `.devin/` and `.windsurf/` roots. Their distinct skill dialects are
preserved after discovery.

[`devin-rules-valid`](rules/devin-rules-valid.md) validates rule YAML,
activation fields, repository-relative glob patterns, and Devin Desktop's
12,000-character workspace-rule limit. Unknown frontmatter keys are accepted
so a newly added Devin field does not break existing repositories.

MCP configuration is read for its servers wherever it lives, so
`mcp-valid-json` and `mcp-prohibited` cover `.cursor/mcp.json`,
`.vscode/mcp.json` and the `mcp` section of an `opencode.json` or
`opencode.jsonc`, plus `mcp-servers` embedded in Copilot custom-agent
frontmatter, as well as
`.mcp.json`. VS Code spells the server map `servers` and adds a sibling
`inputs` array for prompted variables; skillsaw reads the former and ignores
the latter.

Among the editor tools, OpenCode is the one whose *shape* is validated
elsewhere — Agent Plugins also defers, though more broadly, to its own
`agent-plugin-mcp-valid`. OpenCode's transports are named for where the
server runs (`local`/`remote`) rather than for the wire protocol, a local
`command` is an argv array rather than a string, and its environment map is
spelled `environment`, so every field check would misfire. `mcp-valid-json`
stands aside and
[`opencode-config-valid`](rules/opencode-config-valid.md) checks the shape.

Some checks do not defer. Those that hold whatever dialect a file is written
in — a document that is not JSON, a `url` carrying user information, a
credential in a server's `environment`, `headers` or `oauth` map — stay in
`mcp-valid-json` even for a deferred block, which also means they still fire
for a project pinned to a `version:` older than `opencode-config-valid`.
That carve-out is specific to OpenCode; the Agent Plugins deferral is total,
and applies only while `agent-plugin` is among the detected repository
types.

The policy rules are unaffected: `mcp-prohibited` reads OpenCode servers in
the 1.x flat layout under `mcp` *and* the 2.0 nested one under
`mcp.servers`, including a file that carries both at once. Reading only one
layout would let a config hide a server behind the other.

Files that are on-demand rather than always-on — Cursor commands, Copilot
prompt files, Cline workflows, OpenCode commands — are budgeted by
[`context-budget`](rules/context-budget.md) as commands, not as instruction
files, because they enter the context window only when invoked.

### Cursor hooks

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

### OpenCode and APM

`.opencode/` is an editor directory that is also an APM compile target
(`.claude`, `.cursor`, `.gemini`, `.opencode`, `.agents`), so "authored
content" and "build output" have to be told apart. The four readings below
resolve the same way for each of those directories; the evidence is APM's,
never OpenCode's:

- **No `.apm/` and no `apm.yml`** — the repository is native OpenCode.
  `.opencode/` is authored and everything in it is linted in full.
- **APM present with a readable `apm.yml` whose `targets:` omit `opencode`**
  — APM never writes there, so `.opencode/` is hand-written and still linted
  in full. A source tree alone does not make a directory generated. The
  manifest has to be readable for this: a repository with an `.apm/`
  directory and no `apm.yml` at all falls into the last case below, not this
  one.
- **APM present and targeting `opencode`** — `.opencode/` is compiled output
  and APM wins, exactly as it does for `.claude/`. The content findings
  belong on the `.apm/` primitives an author can edit, not on copies the
  next `apm compile` overwrites. The suppression is content-only: the
  security and structural rules still read what actually ships, because a
  generated file can be hand-edited. A skill under the compiled directory is
  not discovered, for the same reason.
- **The `targets:` list cannot be read** — because `apm.yml` is missing,
  unparseable, or declares no `targets:` key. APM keeps the directory:
  answering "not generated" when the manifest cannot say would report every
  finding twice, once on the `.apm/` source and once on its copy. Note that
  an `.apm/` directory alone is enough to make a repository an APM project,
  so a repository with `.apm/` and no `apm.yml` lands here.

A root `opencode.json` or `opencode.jsonc` is never treated as build
output: APM compiles
into `.opencode/`, never over a root config.

This determination is made at the repository root only — `apm_compiled_roots()`
looks for `<root>/.opencode`, nothing deeper. A nested `packages/x/.opencode/`
is always authored content and is always linted in full, whatever `apm.yml`
lists.

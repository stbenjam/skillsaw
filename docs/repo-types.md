# Repository Types

skillsaw automatically detects your repository structure. A repository can match multiple types simultaneously (e.g. an agentskills repo that also has `.coderabbit.yaml`).

A type describes either how the repository *packages* its content — a
marketplace, a plugin, an APM project — or which *tool* it is configured
for. Both are the same kind of fact: if the checkout holds a tool's
configuration, that tool's rules run and `Repo type:` says so. Every value
below is also accepted by `--type`, which replaces packaging-type detection;
tool types are always detected from the checkout, and plugin-contributed
types too.

The tool types sort below the packaging types, so the single "primary" type
in the JSON report's `repo_type` field is unchanged: a marketplace that also
ships a `.cursor/` is still a `marketplace`.

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
| `hooks-dangerous`, `hooks-prohibited`, `codex-hooks-valid` | **Runs (no autofix)** | These commands execute in this checkout. Whoever wrote them, they are this checkout's exposure. |
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

## Muse Code

Repositories with a `.muse/hooks.json`, the committed project hooks
[Muse Code](https://dev.meta.ai/docs/muse-code) reads. skillsaw finds one at
the repository root and in any subpackage, because Muse reads the `.muse/`
layer of the project it is started in; `.muse/worktrees/` holds whole
checkouts Muse made for child agents and is skipped.

Muse uses the nested hooks format Claude Code pioneered, with its own
lifecycle events, matcher-group keys and handler fields.
[`muse-hooks-valid`](rules/muse-hooks-valid.md) checks the file against them.
This matters more than it sounds: Muse prints no diagnostic for anything it
refuses, so a rejected file, a dropped matcher group and a skipped handler
all look like a hook that had nothing to do. The commands themselves are
scanned by [`hooks-dangerous`](rules/hooks-dangerous.md) and
[`hooks-prohibited`](rules/hooks-prohibited.md), including the
`commandWindows` variant.

Muse reads `AGENTS.md` for portable instructions and `.agents/memory/` for
committed team memory. Both are shared conventions rather than Muse
surfaces, so neither is Muse evidence on its own — but both are linted:
`AGENTS.md` wherever it appears, and committed memory at the repository
root, `<repo>/.agents/memory/`, which is where Muse documents it.

## Grok Build

Repositories with a `.grok/` project layer — a `.grok/` directory carrying
any of `rules/`, `skills/`, `agents/`, `commands/`, `hooks/`, `config.toml`,
`lsp.json`, `workflows/`, `roles/`, `personas/` or `sandbox.toml` — the
layer [Grok Build](https://github.com/xai-org/grok-build) reads. An empty
`.grok/` is not detected. skillsaw finds a project layer at the repository
root and in any subpackage, because Grok reads the `.grok/` layer of the
project it is started in.

Most of what is attached is linted by rules that already existed:
`.grok/skills/*/SKILL.md` are portable Agent Skills and get the full skill
rule set, and `.grok/rules/*.md`, `.grok/commands/*.md` and
`.grok/agents/*.md` get the shared content and security rules. Grok reads
each of those three directories at the top level only, so a file nested a
directory deeper is not attached either — it is not context Grok loads.
`.grok/skills/` is the exception and is walked in full. `config.toml` is
parsed as TOML and attached, and the rules that read it come with it.
`lsp.json`, `sandbox.toml`, `workflows/`, `roles/` and `personas/` are
detection evidence only today — nothing under them is read or linted yet;
covering them is later work (see the
[Grok Build design record](https://github.com/stbenjam/skillsaw/blob/main/docs/designs/grok-build.md)).

Three things in that layer are Grok's own structure, on top of the shared
rules above. [`grok-hooks-valid`](rules/grok-hooks-valid.md) validates every
`.grok/hooks/*.json` — Grok merges the whole directory, so a repository may
have several — against Grok's events, alias table and handler fields. This
matters more than it sounds: Grok refuses a whole file over one wrong-typed
field and reports nothing when it does, so a rejected file, a dropped matcher
group and a skipped handler all look like a hook that had nothing to do. The
commands themselves are scanned by
[`hooks-dangerous`](rules/hooks-dangerous.md) and
[`hooks-prohibited`](rules/hooks-prohibited.md).
[`grok-agent-valid`](rules/grok-agent-valid.md) covers the second: a
`.grok/agents/*.md` whose frontmatter is missing, malformed, or without
`name` or `description` is dropped by Grok, and the subagent never appears
in the agent list. The third is `config.toml`, which gets its own paragraphs
below.

Two things in that layer decide whether a file loads at all, and neither
changes what skillsaw lints. Grok gates hooks, MCP and LSP on folder trust —
until a project is trusted they are silently skipped — while skills, rules,
commands and agents load whether or not the folder is trusted. Trust is a
per-machine decision recorded outside the repository, so skillsaw lints the
files as committed. Project MCP servers are declared in `.grok/config.toml`
under `[mcp_servers]` and in the repository-root `.mcp.json`; there is no
`.grok/mcp.json`. skillsaw reads both, so
[`mcp-prohibited`](rules/mcp-prohibited.md) sees a server wherever a Grok
project declared it.

A project `config.toml` contributes only `[mcp_servers]`, `[plugins]`,
`[permission]` and `[mcp] max_output_bytes`. Every other table in it is
dropped, and dropped silently: Grok's unknown-key warnings cover the user's
own `~/.grok/config.toml` and not a project file, so a typo'd table there
produces no diagnostic anywhere. `[plugins] paths` is dropped the same way,
honored only from the user's file.
[`grok-config-project-scope`](rules/grok-config-project-scope.md) reports
that: an ignored top-level table or scalar, `[plugins] paths`, and the
spellings that load nothing at all —
`[[mcp.servers]]`, `[mcp-servers]`, `[mcpServers]`, `[permissions]`,
`transport` inside a server, `defaultMode` inside `[permission]`.
[`grok-config-valid`](rules/grok-config-valid.md) covers the file itself: a
parse error costs every table in it including the ones above the error, and
Grok exits 0 with an empty stderr when that happens, while a malformed
server costs that server and a malformed `[permission]` key costs that key —
or, for a non-table entry inside `rules`, every rule in the array.
Grok reports the server defects through `mcpConfigProblems` and the
permission ones not at all.

Grok reads `AGENTS.md` and `CLAUDE.md` for portable instructions, both of
which carry their own repository types, so a `.grok/` directory is the only
marker that is Grok Build's alone. `.grok/plugins/` holds project-scoped
plugins rather than project configuration, so it is not evidence for this
type; a plugin there is found by the plugin discovery below, like any other.

## Grok Build Plugin

Directories with a `.grok-plugin/plugin.json` manifest, plus every local
source a Grok catalog declares:

```text
my-plugin/
├── .grok-plugin/
│   └── plugin.json       # Optional to Grok, and the marker skillsaw claims
├── skills/
│   └── my-skill/
│       └── SKILL.md
├── commands/
├── agents/
├── hooks/
│   └── hooks.json        # Optional
├── .mcp.json             # Optional: bundled MCP servers
└── .lsp.json             # Optional: not linted yet
```

Grok resolves a manifest from `plugin.json`, then `.grok-plugin/plugin.json`,
then `.claude-plugin/plugin.json`, and reads the first it finds. Two
different questions follow from that chain, and skillsaw answers them
separately.

*Which directory is Grok's* is decided by `.grok-plugin/plugin.json` alone,
or by a Grok catalog listing the directory. The other two spellings are
another ecosystem's declaration — a root `plugin.json` is the Agent Plugins
entrypoint, and `.claude-plugin/` is Claude's — and claiming them would put
every Claude plugin and every portable package under Grok's rules as well.

*Which file Grok reads once the directory is claimed* is the whole chain. So
`grok-plugin-json-valid` reports against a root `plugin.json` or a
`.claude-plugin/plugin.json` when that is the one Grok resolves to — the
finding names the file, and it is the file to open. A directory carrying
both `.grok-plugin/plugin.json` and `.claude-plugin/plugin.json` is both a
Grok plugin and a Claude plugin, and each ecosystem's rules apply
independently to the manifest its own host reads.

A manifest is optional to Grok: a directory holding `skills/`, `agents/`,
`hooks/hooks.json` or `.mcp.json` loads without one. skillsaw still needs a
declaration to attribute the directory to Grok, so a manifest-less plugin is
claimed only when a Grok catalog lists it as a local source.

`hooks` and `mcpServers` accept a path or the object inline; `skills`,
`commands` and `agents` accept a path or an array of paths. All forms are
followed, because a hook written inline runs exactly like one in a file:

| Field | Default location | Also followed |
|---|---|---|
| `hooks` | `hooks/hooks.json` | a declared path, an inline object |
| `mcpServers` | `.mcp.json` | a declared path, an inline server map |
| `skills` | `skills/` | declared directory paths |
| `commands`, `agents` | `commands/`, `agents/` | declared directory paths |

Paths that leave the plugin root are not followed. Grok drops them too, and
silently: a declared `skills` path pointing outside the plugin loads zero
skills while `grok plugin validate` still calls the manifest valid.

Two rules cover the packaging itself.
[`grok-plugin-json-valid`](rules/grok-plugin-json-valid.md) validates the
manifest, and its severities carry the blast radius: a manifest that fails
to load makes Grok skip the whole directory — `skills/` does not rescue it,
and `grok plugin install` still prints success — while a declared path that
escapes or does not exist costs that component list alone.
[`grok-plugin-structure`](rules/grok-plugin-structure.md) covers the
directory: with no manifest and none of `skills/`, `agents/`,
`hooks/hooks.json` or `.mcp.json`, the installer refuses it. `commands/`
alone and `.lsp.json` alone do not count, measured against the binary.

A plugin's `hooks/hooks.json` is scanned by
[`hooks-dangerous`](rules/hooks-dangerous.md) and
[`hooks-prohibited`](rules/hooks-prohibited.md), and its `.mcp.json` by
[`mcp-valid-json`](rules/mcp-valid-json.md) and
[`mcp-prohibited`](rules/mcp-prohibited.md) — inline declarations included.
`grok-hooks-valid` deliberately does *not* see them: Grok loads plugin hooks
through a different adapter from the project layer's, and that adapter
publishes nothing observable about which entries survived, so the failure
scopes that rule reports were measured on `.grok/hooks/*.json` and apply
there only.

## Grok Build Marketplace

Repositories with a Grok catalog at `.grok-plugin/marketplace.json`:

```text
marketplace/
├── .grok-plugin/
│   ├── marketplace.json    # The index Grok reads
│   └── plugin-index.json   # Optional display catalog, read from beside it
└── plugins/
    ├── plugin-one/
    │   └── .grok-plugin/plugin.json
    └── plugin-two/
        └── .grok-plugin/plugin.json
```

Grok looks for a catalog at `.grok-plugin/marketplace.json`, then
`.claude-plugin/marketplace.json`, then a root-level `marketplace.json`, and
reads exactly one. The root spelling is last here and first in the
plugin-manifest order above; the two lookups share no ordering. skillsaw
claims the first for Grok and leaves `.claude-plugin/marketplace.json` to the
Claude `marketplace-*` rules, because the two schemas disagree: Claude
requires `owner`, while a Grok entry carries `category` and a `source` in one
of three shapes. Put a Grok catalog at `.grok-plugin/marketplace.json`.

An entry's `source` names either a directory in this repository or a remote
repository to clone. The local forms are `{"type": "local", "path": "./x"}`
and the bare string `"./x"` — and, measured against the binary, an object
with no discriminator or a misspelled one, because the loader keys on `path`
alone. A `url` is what makes an entry remote, and its own `path` then names a
subdirectory of the clone rather than a directory here. Local sources are
resolved and contained against the marketplace root, so a package that is a
marketplace of its own resolves against the package. Sources that escape
that root are dropped, by Grok and here.

`plugin-index.json` beside the catalog is what the marketplace browser reads
before anything is installed, and a `require_sha` deployment installs from
the `sha` values it publishes. skillsaw attaches it under its catalog.

[`grok-marketplace-json-valid`](rules/grok-marketplace-json-valid.md)
validates the catalog. A catalog Grok cannot parse is discarded whole and
discovery falls back to scanning `plugins/`, so the repository looks healthy
while everything catalogued from anywhere else disappears; an entry with no
`name`, no `source`, or a path that does not resolve is dropped one at a
time, silently. [`grok-marketplace-index-parity`](rules/grok-marketplace-index-parity.md)
compares `plugin-index.json` against the catalog beside it — a `sha` that
has drifted blanks that plugin's component listing — and reports nothing
when there is no index.

A Grok catalog explains its own `plugins/` directory, so a Grok-only
marketplace is not reported as a Claude marketplace with a missing manifest.
Both Grok packaging types are independent of the Claude and Codex types — a
repository commonly ships more than one catalog or manifest, and skillsaw
detects each.

## Google Antigravity

Repositories that configure Google Antigravity's CLI, `agy`. Configuration
lives in a *customization root* — `.agents/`, `.agent/`, `_agents/` or
`_agent/`. `agy` walks up from the directory it was started in to the
repository root and reads every root it finds on the way, so a monorepo
package carries its own layer, and skillsaw attaches each one the same way.

A root holds `hooks.json`, `mcp_config.json`, always-on prose in
`rules/**/*.md`, subagents in `agents/*.md`, portable Agent Skills in
`skills/`, plugins in `plugins/<name>/`, and the registries `agents.json`,
`plugins.json`, `skills.json` and `workflows.json`, each naming where else
to load that kind of customization from.

The root's *presence* is not what detects the type. `.agents/skills/` is the
portable Agent Skills convention every ecosystem reads and `.agents/memory/`
is committed project memory that predates this host, so neither says which
tool a repository configures. Detection needs one of the six named JSON
files, a populated `rules/` or `agents/`, or a `plugins/<name>/plugin.json`
— every one of which skillsaw also attaches, so detection and attachment
agree.

The same directory is where OpenAI Codex publishes a catalog, at
`.agents/plugins/marketplace.json`, with its plugins declaring themselves in
`<name>/.codex-plugin/plugin.json`. The two never collide: Antigravity's
marker is a `plugin.json` at the top of a plugin directory, Codex's is the
`.codex-plugin/` directory inside it, and a catalog file is neither. A
directory both claim keeps both sets of checks — `provenance()` records
every claim, and each ecosystem's format rules read only their own.

Configuration is validated by:

- [`antigravity-hooks-valid`](rules/antigravity-hooks-valid.md): a defect in
  `hooks.json` that drops the whole file, or a key `agy` ignores so the hook
  never runs.
- [`antigravity-mcp-valid`](rules/antigravity-mcp-valid.md): `mcp_config.json`,
  which is startup-fatal when it does not parse and silently drops one server
  when its shape is wrong. [`mcp-valid-json`](rules/mcp-valid-json.md) stands
  its own shape walk down for this file and keeps only its dialect-neutral
  checks — a committed credential and a URL carrying user information.
- [`antigravity-config-json-valid`](rules/antigravity-config-json-valid.md):
  the registry files. Opt-in.

Rules in `<root>/rules/**/*.md` are always-on prose and get the full suite of
content-quality and context-budgeting checks; `<root>/agents/*.md` are
subagents; `<root>/skills/*/SKILL.md` get the Agent Skills rules.

## Google Antigravity Plugin

A direct child of `plugins/` under a customization root — for example
`.agents/plugins/<plugin-name>/` — declaring itself with a `plugin.json`. A
nested `plugins/outer/inner/` is not a plugin, and neither is a directory
named by a sibling catalog but carrying no manifest.

```text
berth-tools/
├── plugin.json           # name, description, disabled, logo
├── skills/               # Agent Skills
│   └── berth-check/
│       └── SKILL.md
├── agents/               # subagents
├── commands/             # converted to skills on install
├── rules/                # prose
├── hooks.json            # lifecycle hooks
└── mcp_config.json       # MCP servers
```

[`antigravity-plugin-json-valid`](rules/antigravity-plugin-json-valid.md)
validates the manifest. It carries four fields that mean anything — `name`,
`description`, `disabled`, `logo` — and every other key, `$schema` and
`version` and `author` included, is discarded by `agy` and reported by
nothing. A package written to the portable
[Agent Plugins](#agent-plugins) schema and dropped in here
is claimed and loaded unchanged.

skillsaw does not follow a `plugin.json` or a plugin directory symlinked out
of the checkout, where `agy` does. Reading a file outside the repository it
was pointed at is a line it does not cross; see
[THREAT_MODEL.md](https://github.com/stbenjam/skillsaw/blob/main/THREAT_MODEL.md), T6.

## OpenAI Codex project configuration

Repositories with a `.codex/hooks.json` or a `.codex/config.toml`, the
project layer Codex reads. This is distinct from a Codex plugin
(`.codex-plugin/plugin.json`) and from a Codex marketplace: it configures the
checkout rather than packaging anything, so it is never treated as a plugin
claim and never exempts the repository from another ecosystem's rules.

Codex reads the layer of every directory between the repository root and the
one a session starts in, so a package's own `.codex/` is live configuration
and every one in the checkout is linted.

Lifecycle hooks come from both files, merged: the `[hooks]` tables of a
`config.toml` get the same checks `hooks.json` gets.
[`codex-hooks-valid`](rules/codex-hooks-valid.md) validates both files and
reports a layer that declares hooks in both, while
[`hooks-dangerous`](rules/hooks-dangerous.md) and
[`hooks-prohibited`](rules/hooks-prohibited.md) scan the commands in them. A
shape defect in `config.toml` stops Codex starting at all, where the same
defect in `hooks.json` costs only that file's hooks; the rule's page records
that asymmetry, and the one check `config.toml` gets and `hooks.json` does
not.

`config.toml` also carries the project's MCP servers, in
`[mcp_servers.<name>]` tables — there is no `.codex/mcp.json` — so
[`mcp-prohibited`](rules/mcp-prohibited.md) inventories them and
[`mcp-valid-json`](rules/mcp-valid-json.md) applies its dialect-neutral
checks, such as a committed credential in an `env` or `http_headers` table.
No rule validates a server table's shape: Codex names the server and the
field and exits 1 over a malformed one itself. Everything else in the file is
Codex settings skillsaw reads nothing from.

`.codex/plugins/` is an install location rather than project configuration —
see [OpenAI Codex Plugin](#openai-codex-plugin) for what runs there.

## Promptfoo

Repositories with promptfoo eval configs (`promptfooconfig*.yaml` or YAML files in `evals/` directories). Prompt strings in the config are treated as content blocks, so all `content-*` rules apply to them automatically. Dedicated `promptfoo-*` rules validate config structure, assertion coverage, and metadata.

## APM (Agent Package Manager)

Repositories with an `.apm/` directory or `apm.yml` file. APM manages dependencies and compiles instruction files for all supported agents (`.claude/`, `.cursor/rules/`, `.github/instructions/`, etc.). When APM is present it is the authoritative source — `.claude/` is treated as compiled output. Package content under `apm_modules/` is externally sourced: it is linted but never autofixed by default, and `lint-external-content: false` omits it from the lint tree.

## Editor and CLI tools

Each tool below is a repository type of its own, detected from the
configuration it reads. Their content is picked up in any repository,
whatever else it is, because it ships in the checkout. Every **prose** file
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
— Cursor, Copilot, Cline, OpenCode, Muse Code, Grok Build and Codex all read it, and one well-linted
AGENTS.md beats five per-vendor copies that drift apart. skillsaw does not
reimplement a per-vendor instruction format on top of it; what it adds is
coverage of the prose each tool keeps in its own directory, plus structural
validation wherever a tool's own metadata can fail silently — see
[`cursor-rules-valid`](rules/cursor-rules-valid.md),
[`cursor-hooks-valid`](rules/cursor-hooks-valid.md),
[`copilot-agent-valid`](rules/copilot-agent-valid.md), and
[`opencode-config-valid`](rules/opencode-config-valid.md).

Each tool is its own repository type, named in the `Type` column. That is
the value `Repo type:` prints, the JSON report lists under `repo_types`, and
`--type` accepts.

| Tool | Type | Files linted |
| --- | --- | --- |
| **Portable** | `agents-md`, `claude-md`, `gemini`, `qwen` | `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `QWEN.md` |
| **Portable skills** | `agentskills` | `.agents/skills/*/SKILL.md` and the other conventional skill directories |
| **Vercel skills CLI** | `skills-lock` | Every `skills-lock.json`, plus matching installed skill payloads unless `lint-external-content: false` |
| **Cursor** | `cursor` | `.cursor/rules/**/*.mdc`, `.cursor/commands/**/*.md`, `.cursor/skills/*/SKILL.md`, `.cursor/mcp.json`, `.cursor/hooks.json`, legacy `.cursorrules` |
| **Copilot / VS Code** | `copilot` | `.github/copilot-instructions.md`, `**/*.instructions.md`, `.github/prompts/**/*.prompt.md`, `.github/agents/**/*.md`, legacy `.github/chatmodes/**/*.chatmode.md`, `.github/skills/*/SKILL.md`, `.vscode/mcp.json` |
| **Cline** | `cline` | `.clinerules` (file), `.clinerules/**/*.md`, `.clinerules/**/*.txt` (excluding `workflows/`, `hooks/`, `skills/`), `.clinerules/workflows/**/*.md`, `.clinerules/skills/*/SKILL.md`, `.cline/skills/*/SKILL.md` |
| **OpenCode** | `opencode` | `opencode.json` or `opencode.jsonc` at the root and in `.opencode/`, `.opencode/commands/**/*.md`, `.opencode/agents/**/*.md`, `.opencode/modes/*.md`, `.opencode/skills/*/SKILL.md`, and the 1.x singular spelling of each (`command/`, `agent/`, `mode/`, `skill/`). Repository-local files matched by `instructions` paths or globs are also linted; remote URLs are not fetched. |
| **Devin CLI / Desktop** | `devin` | `.devin/rules/**/*.md`, `.devin/global_rules.md`, `.devin/skills/*/SKILL.md`, nested `AGENTS.md`/`agents.md`, `AGENTS.local.md`, `AGENT.md`, `CLAUDE.md`; legacy `.windsurf/rules/`, `.windsurf/global_rules.md`, and `.windsurfrules` |
| **Windsurf** | `devin` | `.windsurf/skills/*/SKILL.md` (portable Agent Skills dialect, including nested workspace roots) |
| **Qwen Code** | `qwen` | `QWEN.md`, `.qwen/skills/*/SKILL.md` |
| **Kiro** | `kiro` | `.kiro/steering/*.md` |
| **Google Antigravity** | `antigravity` | `hooks.json`, `mcp_config.json`, `{agents,plugins,skills,workflows}.json`, a populated `rules/` or `agents/`, or a `plugins/<name>/plugin.json`, inside `.agents/`, `.agent/`, `_agents/` or `_agent/` — see [Google Antigravity](#google-antigravity) |
| **Muse Code** | `muse` | `.muse/hooks.json` — see [Muse Code](#muse-code) |
| **Grok Build** | `grok-project` | `.grok/rules/*.md`, `.grok/commands/*.md`, `.grok/agents/*.md`, `.grok/skills/*/SKILL.md`, `.grok/hooks/*.json`, `.grok/config.toml` — see [Grok Build](#grok-build) |
| **OpenAI Codex** | `codex-project` | `.codex/hooks.json`, `.codex/config.toml` — see [OpenAI Codex project configuration](#openai-codex-project-configuration) |
| **Committed project memory** | — | `<repo>/.agents/memory/MEMORY.md` (index) and every `**/*.md` beneath that directory |

`.agents/memory/` is the one row with no type of its own: the convention
predates every tool that reads it and none owns it, so committed memory is
linted without making the repository anything in particular. It is read from
the repository root only — `<repo>/.agents/memory/`, which is where Muse
documents it — and everything below that directory is linted. A copy nested
somewhere else in the tree is not attached, because it is not memory to the
tools that read it either.

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
off the event name rather than off a matcher group — so `claude-hooks-valid`
leaves the file alone and `cursor-hooks-valid` validates the shape instead.
A `type: "prompt"` hook injects text rather than spawning a process, so the
command scanners skip it — but Cursor puts that text into the agent's
context every time the event fires, which makes it shipped instruction
prose. Its `prompt` string is linted as content, so
[`security-hidden-instructions`](rules/security-hidden-instructions.md) and
the other injection scanners read it, and `hooks-prohibited` counts it as a
hook. JSON carries no line numbers, so those findings name the file without
a line.

### Committed project memory

`.agents/memory/` holds notes a team checks into the repository for whatever
agent reads it — the shared counterpart of Claude Code's per-developer auto
memory. The convention belongs to no tool: projects were committing it
before Muse Code shipped, and Muse reads it the way it reads `AGENTS.md`,
injecting `MEMORY.md` in full at session start (even in an untrusted
workspace) alongside the paths of the other Markdown files in the directory,
which it reads on demand. The index is one line per topic by convention;
Muse lists every Markdown file there whether or not the index mentions it.

skillsaw therefore attaches the directory at the repository root
unconditionally, and it is evidence of no tool in particular. The index and
the topic files beside it are agent context, so they get every content and
security rule, and both are budgeted under the `memory` category — the index
because a reader loads it whole, a topic file because a reader loads it
whole once the topic comes up.

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

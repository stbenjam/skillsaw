# Grok Build support

Design record for skillsaw's support of [Grok Build](https://github.com/xai-org/grok-build),
xAI's terminal coding agent. Everything below was verified against Grok Build
**1.0.13 (`5e9a58528b76`, stable)** rather than inferred from documentation.

## The surface

A checkout configures Grok through `.grok/`, and Grok reads the layer of the
project it is started in — the repository root, or a package inside it.

| Path | What it is | How it is read |
|---|---|---|
| `.grok/skills/**/SKILL.md` | Portable Agent Skills | Walked recursively |
| `.grok/rules/*.md` | Always-on project instructions | Flat |
| `.grok/commands/*.md` | Slash commands, loaded as project skills | Flat |
| `.grok/agents/*.md` | Subagent definitions | Flat |
| `.grok/hooks/*.json` | Lifecycle hooks, several files merged | Flat glob |
| `.grok/config.toml` | Project MCP servers, plugins, permissions | TOML |
| `.grok/lsp.json` | LSP servers | JSON |
| `.grok/plugins/<name>/` | Project-scoped plugins | Grok's plugin discovery |
| `AGENTS.md`, `CLAUDE.md` | Portable instructions | Already linted |

Two facts about that table cost work if you get them wrong.

**The flat directories are really flat.** A `.grok/rules/theme/style.md` is not
loaded, and neither is a nested command or agent. Attaching one would budget
context Grok never sees, so the attachment globs do not recurse. `skills/` is
the exception.

**There is no `.grok/mcp.json`.** Grok's MCP sources are `config.toml`
`[mcp_servers]`, `~/.claude.json`, `.cursor/mcp.json`, and the repository-root
`.mcp.json` — which skillsaw already lints. A `.grok/mcp.json` placed in a
trusted project loaded nothing, and the file appears nowhere in the shipped
documentation. Attaching it would have linted a file Grok never reads.

**The trust gate changes nothing about linting.** Hooks, MCP and LSP load only
in a folder the user has trusted; skills, rules, commands and agents load
regardless. Trust is recorded in `~/.grok/trusted_folders.toml`, outside the
repository, so the committed files are linted as committed either way.

## Ecosystem or editor tool — both, split by surface

skillsaw treats these as different problems. An *ecosystem* packages and
installs content, so two of them can claim the same directory and the format
rules need provenance to stay out of each other's trees. An *editor tool* reads
its own configuration locations that nothing else claims, and needs no
provenance machinery at all.

Grok is one of each, and the split runs along the directory name.

`.grok/` is a tool directory. No other ecosystem packages or installs content
into it. A second reader exists — `superagent-ai/grok-cli` keeps its own
project state there, and its hooks loader names a project-level
`.grok/settings.json` only to skip it — but nothing it reads is a surface
skillsaw attaches or a name skillsaw detects on, so there is no directory for
two ecosystems to contend over and nothing for provenance to arbitrate.
`settings.json` stays reserved: do not attach or detect on it. That is the
editor-tool recipe: a `RepositoryType`, a `_TOOL_EVIDENCE` entry, block
classes, an attach loop, no provenance.

`.grok-plugin/` is an ecosystem leg and does need provenance. A single
directory carrying both `.claude-plugin/plugin.json` and
`.grok-plugin/plugin.json` is valid to both tools, and Grok resolves its own
first (`plugin.json` > `.grok-plugin/plugin.json` >
`.claude-plugin/plugin.json`). Grok also reads `.claude-plugin/plugin.json` as
a fallback, so a plain Claude plugin directory is simultaneously a Grok plugin.
That is exactly the situation `RepositoryContext.provenance()` exists for.

skillsaw claims only `.grok-plugin/` for Grok, of the three. The other two
spellings are another ecosystem's declaration, and adopting them would put
every Claude plugin and every portable package under Grok's format rules as
well — a dual claim over content whose author declared one host. The catalog
has its own chain, `.grok-plugin/marketplace.json` >
`.claude-plugin/marketplace.json` > `./marketplace.json`, of which exactly
one is read, and it runs the *opposite* way from the manifest chain: the two
lookups share no ordering.

## The hook failure model

The hooks rule is the larger of the two Grok-specific structural checks (the
other is `grok-agent-valid`, over `.grok/agents/*.md` frontmatter), and its
whole value is the failure-scope model. Grok's file format is the nested
shape Claude Code defined, and its loader's behaviour when something is
wrong is not.

**Method.** An isolated `GROK_HOME` with one hook file per case under
`$GROK_HOME/hooks/` — user scope, always trusted, so no folder-trust gate —
each handler carrying a unique `command` token, read back from `grok inspect
--json`. Every case carries a canary handler in the same group *and* a canary
group under a different event in the same file, so file scope, group scope and
handler scope are told apart rather than assumed. A matrix without those
canaries produces a plausible and wrong answer; that lesson comes from the Muse
Code work, where a single-entry matrix concluded "handler dropped" for two
cases that reject the whole file.

| Input | Scope of the loss | Severity |
|---|---|---|
| A UTF-8 byte-order mark at the start of the file | Whole file | ERROR |
| Malformed JSON | Whole file | ERROR |
| `NaN` / `Infinity` / `-Infinity` anywhere | Whole file | ERROR |
| No top-level `hooks` object, or a non-object one | Whole file | ERROR |
| An event whose value is not an array | Whole file | ERROR |
| A group that is not an object, or has no `hooks` array | Whole file | ERROR |
| A `matcher` that is not a string | Whole file | ERROR |
| A handler that is not an object, or has no `type` | Whole file | ERROR |
| A `type` of `null`, which reads as no `type` | Whole file | ERROR |
| A known field of the wrong JSON type (`null` excepted) | Whole file | ERROR |
| A `timeout` above `2**64-1` | Whole file | ERROR |
| A `matcher` that does not compile | That matcher group | WARNING |
| An unknown event name | That event's entries | WARNING |
| A `command` handler with no `command` | That handler | WARNING |
| An `http` handler with no `url` | That handler | WARNING |
| A `command` of `null`, or a `url` of `null` on `http` | That handler | WARNING |
| A `type` other than `command` / `http` | That handler | WARNING |
| `env` naming a runner-reserved variable | Stripped; the handler runs | INFO |
| `matcher` on `Stop` / `UserPromptSubmit` | Kept, never consulted | INFO |
| An unknown handler, group or top-level key | Tolerated | — |
| A `null` `timeout`, `env`, `matcher` or unneeded `url` | Read as absent | — |

The whole-file cases are why the rule is ERROR: one mistyped `timeout` silently
costs the author *every* hook in the file, including the ones under other
events. `grok inspect --json` reported `configWarnings: null` in every failing
case, so the runtime gives no diagnostic at all and static lint is the only
signal.

Two findings from the same matrix shape the rule as much as the table does.

**The alias table is irregular, and accepting all of it is a correctness
requirement.** Grok accepts the `snake_case` spelling of every event, the
`camelCase` spelling of every event *except* `userPromptSubmit`, its own
`SubagentEnd`, and Cursor's nine per-operation names. A missing entry is a
false "unknown event" on a working file, and the one exception cannot be
derived from a naming rule — it has to be measured.

**Matchers are Rust regexes, and only on the events that use them.** `\p{L}+`
and `[a-z&&[^aeiou]]` load; `(?<=x)y` and `(a)\1` drop their groups. `""` and
`"*"` are catch-alls Grok special-cases rather than compiles. On `Stop` and
`UserPromptSubmit` the matcher is never compiled at all, so even an
uncompilable one there costs nothing — which is why that case is advisory and
the syntax check does not run. skillsaw shares the Rust-dialect check with the
Muse Code rule rather than keeping two copies.

**Two tables carry the ERROR findings, and neither has an override.** An
unknown event is a WARNING scoped to that event, and `extra-events` lets a
project name one newer than its skillsaw. `HANDLER_FIELDS` and
`HOOK_HANDLER_TYPES` in `formats/grok.py` are different: a handler type or a
field's JSON type outside them is a whole-file ERROR, and a hooks file is
JSON, so the only relief is `.skillsaw.yaml`. Re-measure both tables — and
`PLUGIN_NAME_RE`, `SHA_LENGTHS` and `COMPONENT_PATHS` beside them — against
every Grok minor release before anything else in this record. If Grok ever
accepts a third handler type or relaxes a field's type, an
`extra-handler-types` option mirroring `extra-events` is the shape of the fix.

## What the packaging loader costs

Every row measured against 1.0.13 rather than read off the docs, because the
loader reports none of it. The scope column is the whole basis for each rule's
severity.

| Input | Scope of loss |
|---|---|
| `plugin.json` that fails to parse, or a `name` outside `PLUGIN_NAME_RE` (1-64 chars, lowercase alphanumeric and hyphens, no leading or trailing hyphen) | The whole plugin directory, skipped at discovery. `grok plugin install` still prints success; `grok inspect` then shows `plugins: []` |
| A `skills`/`commands`/`agents` path that escapes the plugin root or does not exist | That component list. Containment is enforced, not incidental: a target that exists outside the plugin is still dropped |
| A `skills`/`commands`/`agents` declaration beside a populated conventional directory | Everything under the conventional directory: the declaration **replaces** it. Measured for all three — `{"commands": "custom-commands"}` beside a populated `commands/` loaded only `custom-commands` |
| `hooks` or `mcpServers` as an array | Those hooks or servers. The field is one path or one inline object; a list-valued `hooks` loaded as an empty inline document and a list-valued `mcpServers` loaded nothing |
| A url source's `sha` outside 40 or 64 hex | The install, refused with "git commit SHA must be 40 or 64 hexadecimal characters". Case-insensitive at the runtime; the upstream validator requires 40 lowercase |
| A catalog entry with no `name`, no `source`, or a `path` that does not resolve or escapes the marketplace root | That entry, silently |
| Two catalog entries resolving to one manifest name | The plugin becomes uninstallable by name: `Multiple marketplaces provide a plugin named "canary"`, and both suggested qualifiers are identical |
| A catalog that fails to parse, or whose `plugins` is not an array | The whole catalog — and discovery falls back to scanning `plugins/` only, so a repository keeping third-party plugins anywhere else loses exactly those |
| `plugin-index.json` whose `sha` disagrees with the catalog entry's | The component listing for that plugin, blanked in the browser |
| An empty directory, or one holding only `commands/` or only `.lsp.json` | The install, refused with "no plugins found in the source" — even though both are documented components and both load once the directory is installed |

## Shipping order

Three pull requests, in dependency order, because the three halves have
genuinely different review surfaces.

**PR 1 — project surfaces and hooks.** Detection, attachment, the reuse that
follows from it, `grok-hooks-valid` and `grok-agent-valid`. This is the one
that converts `Skills: 0` into full skill, content and security coverage for
`.grok/`: the single line adding `.grok/skills` to `CONVENTIONAL_SKILL_DIRS`
earns ten skill rules, and attaching the prose earns every content and
security rule. No new rule was written for any of that.

**PR 2 — plugins and marketplace.** The provenance leg, `discovery/grok.py`,
and four rules over `.grok-plugin/plugin.json`, `marketplace.json` and
`plugin-index.json`. Separate because provenance is the part that can break
other ecosystems' results, and it should be reviewed against the dual-manifest
evidence on its own.

One thing the leg does not do is hand plugin hooks to `grok-hooks-valid`. A
plugin's `hooks/hooks.json` gets its own block class, because Grok loads it
through a different adapter and 1.0.13 publishes no observable for that path:
a plugin's hooks file reports one opaque entry whether it is valid, empty or
unparseable, so the failure scopes measured on `.grok/hooks/*.json` are not
evidence about it. `hooks-dangerous` and `hooks-prohibited` read the shared
base and see both.

**PR 3 — `.grok/config.toml`.** The highest-signal config check there is: only
`[mcp_servers]`, `[plugins]`, `[permission]` and `[mcp] max_output_bytes` are
honored at project scope, and everything else a developer writes there is
silently ignored — a project config declaring `[model]`, `[ui]` and `[sandbox]`
alongside the four loaded the four and reported no warning. Separate because it
needs a TOML parser: `tomllib` is stdlib only from Python 3.11 while skillsaw
supports 3.9, so it carries a new conditional `tomli` dependency that deserves
its own argument.

## Deliberately out of scope

| Surface | Why |
|---|---|
| `.grok/workflows/*.rhai` | Needs a Rhai parser; a regex over a scripting language generates false positives |
| `.grok/sandbox.toml` | TOML dependency, and the semantics misfire easily — `read_only`/`read_write` are literal directory grants, not globs |
| `.grok/roles/*.toml`, `.grok/personas/*.toml` | TOML dependency; the formats are less settled |
| `.grok/lsp.json` | No public schema to calibrate against. Detection evidence only |
| `~/.grok/` runtime state, `trusted_folders.toml`, `known_marketplaces.json` | Host-machine state, not repository-resident |

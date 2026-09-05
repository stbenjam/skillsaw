# Grok Build

<!-- Repo-root-relative src/... paths below are intentionally kept as prose, not navigable links. -->
<!-- skillsaw-disable content-unlinked-internal-reference -->

Grok Build is xAI's terminal coding agent. A checkout configures it through `.grok/`.
Most of that layer is shared convention other tools read too — portable Agent Skills,
Markdown prose, `AGENTS.md` — so what skillsaw validates that is Grok's alone is its
lifecycle hooks, its subagent frontmatter, and the plugin and marketplace files its
installer reads.

## Upstream source(s)
- The user guide shipped with 1.0.13: `10-hooks.md` (events, the Cursor alias table,
  handler fields, reserved environment variables, the matcher-per-event table),
  `12-project-rules.md` (the `.grok/` layer), `07-mcp-servers.md` (MCP sources),
  `08-skills.md`, `04-slash-commands.md`, `16-subagents.md`, `26-config-reference.md`.
- The shipped executable, whose hook loader is
  `crates/codegen/xai-grok-hooks/src/config.rs`. Its diagnostics name the handler
  contract directly: `command handler requires a 'command' field`, `http handler
  requires a 'url' field`, `hooks: skipped unrecognized event names (check for typos).`,
  and `hook env: ignoring user-supplied value for runner-reserved key (the
  runner-injected value always wins)`.

The docs name the events and the file locations, and everything below was verified
against Grok Build 1.0.13 (`5e9a58528b76`, stable) rather than taken from them. Method:
an isolated `GROK_HOME` (the real `~/.grok` untouched) with one hook file per case
under `$GROK_HOME/hooks/` — user scope, always trusted, so no folder-trust gate — each
handler carrying a unique `command` token, read back from `grok inspect --json`. Every
case carries a canary handler in the same group and a canary group under a different
event in the same file, so file, group and handler scopes are told apart rather than
assumed. `grok inspect --json` reported `configWarnings: null` for every failing case:
the runtime tells the author nothing, which is why `grok-hooks-valid` exists. Re-run
that matrix before changing a rule here.

## What to check
- **Hooks files**: `<project>/.grok/hooks/*.json`, read as a **flat glob** and merged.
  A file in a subdirectory and a file under another extension are both ignored. User
  hooks live in `~/.grok/hooks/` and config hooks in `config.toml`; neither is in the
  repository.
- **Shape**: the nested form Claude Code defined —
  `{"hooks": {Event: [{matcher?, hooks: [handler, ...]}, ...]}}`. Top-level keys other
  than `hooks` are ignored, as are unknown matcher-group keys (`description`) and
  unknown handler keys.
- **Failure scope** is the thing to get right, because it is what the diagnostic is
  worth:
  - *Whole file*: a UTF-8 byte-order mark at the start of the file (`grok inspect
    --json` loaded zero hooks from an otherwise-correct file with a leading BOM;
    skillsaw reads with `utf-8-sig` and would see a valid document, so this is
    checked before anything else); malformed JSON; a bare `NaN`/`Infinity`/`-Infinity`;
    no top-level `hooks` object, or one that is not an object; a recognized event
    whose value is not an array; a matcher group that is not an object; a group with
    no `hooks` key or
    a non-array one; a `matcher` that is not a string, which never reaches the regex
    compiler; a handler that is not an object; a handler with no `type`, or a `null`
    one; any known handler field carrying the wrong JSON type — including a `timeout`
    above `2**64-1`, the field's own `u64` ceiling, which fails the same way as a float
    or a negative even though the value is a plain non-negative integer. A JSON `null`
    is not one of those wrong types: Grok reads it as the key being absent, so `type`
    is the only field whose `null` costs the file.
  - *That group*: a `matcher` string that does not compile.
  - *That event's entries*: a name outside the events and aliases below. Unknown
    events are skipped before their values, groups or handlers are decoded.
  - *That handler*: a `command` handler with no `command` or a `null` one, an `http`
    handler with no `url` or a `null` one, a `type` outside `command`/`http`.
  - *Tolerated*: a `null` `timeout`, `env` or `matcher`, and a `null` in any field the
    handler's type does not require — each is the key being absent.
- **Events** (15): `SessionStart`, `SessionEnd`, `UserPromptSubmit`, `PreToolUse`,
  `PostToolUse`, `PostToolUseFailure`, `PermissionDenied`, `Stop`, `StopFailure`,
  `StopCancelled`, `Notification`, `SubagentStart`, `SubagentStop`, `PreCompact`,
  `PostCompact`.
- **Aliases**, all normalized and all accepted — a missing one is a false "unknown
  event" on a working file: `SubagentEnd`; the `snake_case` spelling of all 16 names —
  the 15 events above plus `subagent_end`, which is itself an alias for
  `SubagentStop`;
  the `camelCase` spelling of every event **except** `userPromptSubmit`, which is not
  accepted; and Cursor's per-operation names (`beforeShellExecution`,
  `beforeMCPExecution`, `beforeReadFile` → `PreToolUse`; `afterShellExecution`,
  `afterMCPExecution`, `afterFileEdit`, `afterAgentResponse`, `afterAgentThought` →
  `PostToolUse`; `beforeSubmitPrompt` → `UserPromptSubmit`).
- **Handler types**: `command` (a shell command) and `http` (the event envelope POSTed
  to a URL).
- **Handler fields**, with the JSON type each must carry: `type`, `command`, `url`
  (strings); `timeout` (non-negative integer — a float, a negative, a bool and a
  numeric string each refuse the file, while a large value is fine because `Stop` and
  `SubagentStop` default to 600 seconds); `env` (an object of strings). A wrong type on
  any of them refuses the file; a `null` is read as the key being absent; a key outside
  the table is tolerated.
- **Matchers**: compiled at load with Rust's `regex` crate — verified by loading
  `\p{L}+` and `[a-z&&[^aeiou]]`, which Python's `re` rejects, and by watching
  `(?<=x)y` and `(a)\1` drop their groups. `""` and `"*"` are catch-alls, not patterns.
  On `Stop` and `UserPromptSubmit` the matcher is kept in the configuration and never
  compiled, so even an uncompilable one there costs nothing.
- **Reserved `env` keys**, stripped at load with the runner's value winning:
  `GROK_HOOK_EVENT`, `GROK_HOOK_NAME`, `GROK_SESSION_ID`, `GROK_WORKSPACE_ROOT`,
  `CLAUDE_PROJECT_DIR`. A plugin's hooks additionally get `GROK_PLUGIN_ROOT`,
  `GROK_PLUGIN_DATA` and their two `CLAUDE_` aliases.
- **The rest of the layer**: `.grok/skills/**/SKILL.md` (walked recursively),
  `.grok/rules/*.md`, `.grok/commands/*.md` and `.grok/agents/*.md` (each read **flat**
  — a nested file is not loaded). A `.grok/commands/<n>.md` is loaded as a project
  *skill*, which is why `grok inspect` lists it among the skills. The skill-location
  table in `08-skills.md` calls that directory "legacy command markdown", which is
  where `GrokCommandBlock`'s docstring gets the word.
- **Subagent frontmatter**: `.grok/agents/*.md` needs `name` and `description` in
  frontmatter or Grok's loader drops the subagent and reports nothing — it is on
  disk and simply absent from the agent list. An empty value for either key still
  registers; scalars, including numbers, booleans and null, are coerced to strings,
  but collections are rejected. Leading whitespace and delimiter-line suffixes are
  accepted. Extra keys are tolerated.
  `.grok/commands/*.md` is deliberately not held to the same demand — Grok loads a
  frontmatter-less command file, naming it from the filename, so the same check
  there would be a false positive on a file that works.
- **Trust gate**: hooks, MCP and LSP require folder trust (`/hooks-trust`, `--trust`,
  or `GROK_FOLDER_TRUST=0`); skills, rules, commands and agents load unconditionally.
  Trust is recorded in `~/.grok/trusted_folders.toml`, outside the repository, so it
  changes nothing about what skillsaw lints.
- **There is no `.grok/mcp.json`.** Grok's MCP sources are `config.toml`
  `[mcp_servers]`, `~/.claude.json`, `.cursor/mcp.json` and the repository-root
  `.mcp.json`. A `.grok/mcp.json` placed in a trusted project loaded nothing, and the
  file appears nowhere in the docs. Do not attach it.

## Project `config.toml`
One file read at four layers, of which the project layer is the narrow one. The
shipped `26-config-reference.md` says so twice — "Project `.grok/config.toml`: only
`[mcp_servers]`, `[plugins]`, `[permission]`, and `[mcp] max_output_bytes`" — but the
documented four are not equally real when measured against 1.0.13.

**Where Grok is silent, and where it is not.** `configWarnings` is a *user-layer*
diagnostic: a typo'd table or key in a project file is invisible in every observable
Grok offers, and its own warning list is not a trustworthy oracle anyway (it calls
`hooks` unrecognized while the hook loads, and `mcp` unrecognized though the reference
documents `mcp.max_output_bytes`). The one exception is `mcpConfigProblems`, which *is*
produced for project-scope `[mcp_servers]` entries — a bad server shape, an unknown
server field. So Grok already tells an author about bad MCP shapes and tells them
nothing about ignored tables or bad permission shapes, which is where a rule adds the
signal.

### What a project file contributes

- **Measured honored**: `[mcp_servers]` and `[permission]`
  (`PROJECT_CONFIG_TABLES_MEASURED`). `[plugins]` additionally has source-confirmed
  project support; `[mcp] max_output_bytes` remains documented but unmeasured.
  `PROJECT_CONFIG_TABLES` holds all four.
- **Measured refused**: `[hooks]` (the honored path for a project's hooks is
  `.grok/hooks/*.json`, which loads), `[skills].paths` and `[sandbox].profile`, each
  with a positive user-scope control (`PROJECT_CONFIG_TABLES_REFUSED`).
- **`[plugins]`**: the live session's `resolve_effective_plugins_config()` merges
  trusted project `paths` and project `disabled`. `inspect` does not call that
  resolver, so its absent project plugins cannot establish a refusal. The source
  is `xai-grok-shell/src/config/mod.rs` at
  `72a61251fcffb464bcc687aeb5a998e5a98ec0c9`; no authenticated session was needed.
  Config paths name individual plugins with separate component trust; they skip
  installer child-bundle search. User-scope `inspect` confirms root `plugin.json`,
  custom skill paths, absolute paths and `.`; empty strings are skipped.
  Native strings are session-cwd-relative. Static discovery
  assumes a session launched beside each declaring `.grok/`, including nested
  project roots, and contains targets within the lint checkout. It does not expand
  environment variables or `~`, inspect external user configuration, or infer trust.
  These declarations feed the shared provenance and skill-discovery claim set even
  under unrelated `--type` overrides. Installer-only structure advice skips paths
  declared solely for direct loading; catalog-addressed paths retain that check.
- **User scope**: `GrokConfigBlock.is_user_config` matches the actual configured
  user file by canonical path, as `xai-grok-workspace/src/project_config.rs` does.
  Project-only advice skips that file while TOML and MCP validation keep it.
  A dotfiles checkout elsewhere is not guessed to be user configuration.

### `[mcp_servers]`

- **Fields**: `MCP_SERVER_FIELDS` is the accepted set; an unknown
  field raises an `mcpConfigProblems` *warning* and the server still loads, so it is
  never a reason to call the file broken. `transport` is the plausible misspelling of
  `type` and is not an alias — reported unrecognized, ignored.
- **Transport derivation** (`formats/grok_mcp.py`): Grok tries the entire stdio
  variant first, then HTTP. Fields outside the selected variant are ignored;
  malformed stdio fields can allow HTTP fallback. Common fields (`enabled`,
  timeouts, OAuth and setup) decode independently. A selected blank connection is
  rejected only when enabled. The URL accepts `url`, `urlTemplate` or `url_template`;
  two URL aliases reject the HTTP variant. HTTP becomes SSE for case-insensitive
  `type = "sse"` or an exact `/sse` URL suffix. Neither target's content or
  reachability is validated. `GrokConfigBlock` normalizes the selected variant,
  including aliases, while retaining disabled and unresolved-setup definitions for
  diagnostics. Native `inspect` omits those definitions. These decoding controls
  were verified against Grok 1.0.13 and the pinned config-types MCP source.

### `[permission]` and the spellings that load nothing

- **`[permission]`**: `allow`/`deny`/`ask` hold compact rule strings and `rules` holds
  verbose entries. Any array-valued compact key selects the compact branch,
  even an empty array; malformed compact keys alone do not suppress verbose rules.
  Empty verbose lists need no lost-rule warning. The workspace resolver's verbose
  types are owned by `formats/grok_permissions.py`: action is required, tool defaults
  to any, pattern is an optional string, and pattern_mode defaults to glob. Wrong
  enum spellings or known field types discard the entire verbose list. Grok's TOML
  unit-enum and positional-struct forms are supported. An unparseable compact rule
  string costs only that entry.
  A **wrong-typed entry** splits by key, measured: a non-string in a list key costs
  that entry (`allow = ["Bash(git *)", 42]` loaded 1), while a non-table in `rules`
  costs the whole array (two valid rules beside a bare integer loaded 0).
  `defaultMode` is a `.claude/settings.json` key with no meaning here.
- **Silent misspellings**, each loading nothing and saying nothing: `[[mcp.servers]]`,
  `[mcp-servers.<n>]`, `[mcpServers.<n>]`, and `[permissions]` (plural, which also
  drops the file out of `permissions.sources`).

### Parsing

- **Malformed TOML** — a syntax error, a duplicate key, a duplicate table header — is
  **whole-file**, including tables above the error. Grok exits 0 with an empty stderr;
  the sole signal is a `configSources[].note` of `"parse error"` in `grok inspect`. An
  empty file reads as `note: "empty"`.
- **Parsing**: `read_toml()` in `src/skillsaw/utils.py`, `tomllib` on 3.11+ and `tomli`
  below it. Errors are file-level: stdlib `tomllib` gained `TOMLDecodeError.lineno`
  only in 3.14, so 3.11 through 3.13 carry no position, while the floor's `tomli`
  2.2.1 does expose one — and one contract across both parsers beats a line number
  on some legs. A leading UTF-8 BOM is stripped by `read_text` before the parser
  sees it.
- **Do not claim** that `mcpServers[].source.path` attributes a server to its config
  file: it always prints the user `$GROK_HOME/config.toml` path, even for project-only
  servers and even when that file does not exist.

## Plugins and the marketplace
A plugin bundles skills, commands, agents, `hooks/hooks.json`, `.mcp.json` and
`.lsp.json` into one installable directory; a marketplace is a repository listing
plugins in `.grok-plugin/marketplace.json`. Both were verified against 1.0.13 by
building catalogs and plugins in an isolated `GROK_HOME` **and** an isolated `HOME` —
`GROK_HOME` alone is not enough, because Grok also reads `~/.claude/settings.json`
`extraKnownMarketplaces` and will start cloning the real marketplaces listed there.
`GROK_FOLDER_TRUST=0` is the *permissive* setting, and `projectRoot` is set only inside
a git repository.

- **Manifest resolution**: `plugin.json` > `.grok-plugin/plugin.json` >
  `.claude-plugin/plugin.json`, first match wins. **Catalog resolution**:
  `.grok-plugin/marketplace.json` > `.claude-plugin/marketplace.json` >
  `./marketplace.json`, exactly one read, never merged. The root spelling is last here
  and first in the manifest order; the two lookups share no ordering, so do not derive
  one from the other.
- **skillsaw claims only the `.grok-plugin/` spelling of either.** The others are
  another ecosystem's declaration, and adopting them would put every Claude plugin and
  every portable package under Grok's format rules too.
- **A manifest is optional.** A source root holding `skills/`, `agents/`,
  `hooks/hooks.json` or `.mcp.json` installs without one, under a synthesized
  `<dir>-<hash>` name. Directory presence is sufficient. Otherwise the installer
  checks immediate non-symlink child directories for manifests or those conventions;
  an accepted child bundle does not use the parent/hash name. `commands/` alone and
  `.lsp.json` alone are refused. Skillsaw claims a manifest-less directory only when
  a catalog lists it as a local source.
- **Manifest failure scope**: unparseable JSON, a rejected known field type, or a
  `name` that is missing, non-string or outside
  `\A[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?\Z` makes **runtime registration** skip the
  plugin directory. Installation is a separate consumer: `try_load_plugin` falls
  back to conventional components after a manifest error, so `skills/` can make
  installation succeed even though runtime registration rejects the manifest.
  A declared path that escapes the plugin root after canonical resolution, does not
  exist or has the wrong target kind costs that component only. Contained parent,
  absolute and empty-root directory paths are valid. An override *replaces* the
  conventional directory rather than extending it. A name disagreeing with the
  directory name, a non-semver string `version`, an unknown key and a bare string
  where an array is allowed all cost nothing. Recognized struct duplicates reject;
  ignored metadata and inline object duplicates keep their accepted map behavior.
- **`hooks` and `mcpServers` are `path | inline JSON`**. An array is decoded as an
  inline value, not a list of file paths. So
  `"hooks": "not-an-object"` is read as a path, found missing, and dropped silently — it
  is not a type error. A malformed inline `hooks` costs the hooks only; the sibling
  `mcpServers`, the skills and the plugin survive.
- **Catalog failure scope**: the catalog and every entry require a string `name`;
  empty strings are accepted. A missing/non-string name, invalid known field type,
  parse error or present non-array `plugins` discards the whole catalog. Omitted
  `plugins` defaults to an empty array. A missing/null `source`, a local `path` that
  does not resolve, or a path rejected by the source grammar drops only that entry.
  When the whole catalog fails, native discovery falls back to scanning `plugins/`
  only, so a repository keeping third-party plugins under `external_plugins/` loses
  exactly those with no diagnostic. **Two entries resolving to one manifest name** are not deduplicated:
  install fails with `Multiple marketplaces provide a plugin named "canary"` and both
  suggested qualifiers are identical, so the plugin is uninstallable by name.
- **Local sources are keyed on `path` alone.** `{"type": "local", "path": …}`,
  `{"source": "local", …}`, a bare string, an object with **no** discriminator, and one
  with a **bogus** `type` all install identically. Requiring a discriminator is a false
  positive. A non-null `url`, including an empty string, selects remote handling;
  an absent/null URL leaves `path` local regardless of the discriminator. A remote
  `path` names a subdirectory of the clone. Catalog paths normalize backslashes,
  allow one leading `./`, and reject root, empty, dot, parent and colon-containing
  components. Plugin manifest component paths use the separate canonical contract.
- **Install pins**: catalog decoding checks `sha`/`ref` types, but pin shape is checked
  at installation. An explicit non-null `sha` takes precedence even when empty or
  invalid. With absent/null `sha`, a full 40- or 64-hex `ref` becomes the pin; other
  refs remain unpinned. Pin matching trims Rust whitespace and accepts either case.
  With no explicit SHA and no full-commit ref, the clone remains unpinned; an invalid
  explicit SHA is refused. The upstream `validate-catalog.py` requires lowercase
  40-hex, stricter than the installer.
- **`plugin-index.json`** is the sole source of the pre-install component listing, and
  it has independent precedence: `.grok-plugin/plugin-index.json`, then
  `.claude-plugin/plugin-index.json` only when the preferred file is absent. A
  present broken preferred file blocks fallback; a legal shadowed copy is not a
  placement defect. For a URL source it is gated on exact `sha` string equality with
  the catalog entry — drift silently blanks the listing, and an absent catalog SHA
  supplies no remote components even when `ref` pins installation. Index keys use
  literal catalog entry names, including empty strings, rather than resolved manifest
  names. Local sources ignore index SHA, so a stale index can be displayed while the
  plugin on disk disagrees. An index entry with no catalog entry, and a malformed
  index, are both ignored silently.
  The typed reader requires integer version `1`, defaults omitted `plugins` to
  an empty map, and requires each entry's component structure. One bad nested
  field invalidates the whole index. The decoder preserves measured positional
  JSON struct arrays, unknown fields and map duplicate semantics; recognized
  struct duplicates and a BOM are rejected.
- **Plugin hooks are a different loader from the project layer's.** `grok inspect
  --json` reports one opaque entry for a plugin's `hooks/hooks.json` whether the file is
  valid, empty or unparseable, so the failure matrix above is **not** evidence about it.
  That is why plugin hooks attach as `GrokPluginHooksBlock`, a sibling of
  `GrokHooksBlock` rather than a subclass, and `grok-hooks-valid` never sees them.
  `hooks-dangerous` and `hooks-prohibited` read the shared `HooksBlock` base and do.

### skillsaw code for this
- Vocabulary (marker names, both resolution orders, the name and `sha` patterns, the
  component table, the manifest readers) — `src/skillsaw/formats/grok.py`.
- Discovery — `src/skillsaw/discovery/grok.py`, state-free: catalog enumeration, local
  sources, plugin directories. The `.grok-plugin` directories come from the one
  repository walk (`PLUGIN_MARKER_DIR_NAMES` in `discovery/detect.py`), so a plugin or a
  catalog in a monorepo package is found without a second traversal.
- Caching and the `--type` gate — `RepositoryGrokMixin` in
  `src/skillsaw/repository_grok.py`, mixed into `RepositoryContext`. It lives outside
  `context.py` because `tests/test_module_layering.py` caps that file at 900 lines.
- Ownership — one branch in `RepositoryContext.provenance()`
  (`src/skillsaw/repository_provenance.py`) adding `"grok"`, plus `grok_only`, which
  `_declares_containment` reads to draw the package-containment boundary: a Grok plugin
  contains its own files, and a directory Claude also declares stays on Claude's looser
  reading. `is_grok_only_plugin` and `in_grok_only_plugin` are the per-path views of it;
  `mcp-valid-json` reads the second where the block class cannot answer — a repo-root
  plugin's conventional `.mcp.json` is attached before any plugin cluster runs — and
  only ever *tightens* a check there.
- Lint tree — `GrokPluginNode`, `GrokPluginConfigNode`, `GrokMarketplaceConfigNode` and
  `GrokMarketplaceIndexNode` in `src/skillsaw/lint_target.py`; `GrokPluginHooksBlock`,
  `GrokMcpBlock`, `GrokInlineHooksBlock` and `GrokInlineMcpBlock` in
  `src/skillsaw/blocks/json_config.py`; all attached in the one plugin pass in
  `src/skillsaw/lint_tree.py`. A dual-manifest directory keeps the class the other
  ecosystem's branch already attached, so one file never gets two blocks.
- Types — `RepositoryType.GROK_PLUGIN` and `GROK_MARKETPLACE` in
  `src/skillsaw/repository_types.py`, both in `SKILL_REPO_TYPES` and neither in
  `TOOL_REPO_TYPES`.

There is deliberately no Grok install-root helper. Codex has one because
`.codex/plugins/` holds plugins a developer installed into their own checkout, which
autofix must not rewrite. Grok's repository-resident location, `.grok/plugins/`, is
documented as "Project, shared through version control" — authored content — and its
auto-trusted counterpart `~/.grok/plugins/` is never in a checkout.

## skillsaw rules that map
- Hooks — `src/skillsaw/rules/builtin/grok/`: `grok-hooks-valid`.
- Subagents — `src/skillsaw/rules/builtin/grok/`: `grok-agent-valid`, the `name` and
  `description` Grok's loader registers a `.grok/agents/*.md` by. Both must be
  present and scalar; empty and null values register, collections do not.
- Project `config.toml` — `src/skillsaw/rules/builtin/grok/`: `grok-config-valid`
  (ERROR) reports the parse error that costs the whole file. Per-server and
  per-key defects default to WARNING and honor explicit rule severity. These
  defects cost a server, key or verbose rule list. Server checks follow the ordered
  transport decoder, including aliases, fallback and disabled-server blank values.
  Permission checks follow compact-array precedence and whole verbose-list typing;
  non-array compact keys do not suppress verbose rules. It never
  reports an unknown server field or an unknown permission key, both of which load.
  `grok-config-project-scope` (WARNING, option `extra-tables`) reports what the
  project layer drops: a top-level table or scalar outside `PROJECT_CONFIG_TABLES`
  (only `hooks` carries a hint — it is the one refusal with somewhere else in the
  repository to go — and the rest are one consolidated finding), and the silent
  misspellings. Unknown keys inside `[plugins]` or `[mcp]` stay open, and
  `extra-tables` reaches top-level names only. Trusted project plugin paths
  follow the live resolver described above; the actual user config is exempt
  from project-only advice.
- Plugin manifests — `grok-plugin-json-valid` (ERROR): invalid JSON/BOM, rejected
  typed fields or recognized duplicates, and a `name` that is missing, non-string,
  empty or outside `PLUGIN_NAME_RE`, each preventing runtime registration.
  Installation's convention fallback is separate. Component paths that escape after
  canonical resolution, do not exist or have the wrong target kind, and an
  override replacing the conventional directory, are WARNING; a non-semver `version`
  and an absent `description` are INFO. It reports no unknown key, no name/directory
  disagreement, and no bare string where an array is allowed.
- Plugin directories — `grok-plugin-structure` (WARNING): no manifest and none of
  `skills/`, `agents/`, `hooks/hooks.json` or `.mcp.json` at the source root or
  an immediate child plugin. Directory existence is sufficient for installation;
  nested content and placeholders do not make it uninstallable. One INFO for a
  convention-based source root a catalog addresses by name, since it installs as
  `<dir>-<hash>`; child bundles do not receive that parent-name advice.
- Catalogs — `grok-marketplace-json-valid` (ERROR): whole-catalog parse/BOM,
  recognized duplicate and typed-field defects, including a non-object root,
  missing/non-string catalog or entry `name`, and present non-array `plugins`.
  Omitted `plugins` defaults to empty, and empty names are accepted. Entry-local
  source failures and the configured full-pin policy are checked after decoding.
  Remote `path` shape and a source object naming neither `path` nor `url` are
  WARNING; a pin the installer accepts but the upstream validator refuses — 64 hex
  or uppercase — is INFO. No source discriminator is required.
- Index parity — `grok-marketplace-index-parity` (WARNING): one consolidated finding
  per selected `plugin-index.json` for literal catalog-name keys, exact remote `sha`
  and local skill drift; one for a malformed selected index; and one for an unsupported
  index placement. Selection uses the independent `.grok-plugin` then `.claude-plugin`
  fallback order above, not the catalog's directory. Legal shadowed copies and absent
  indexes are silent.
- Vocabulary (events, aliases, handler fields, reserved env, failure scopes) — one
  module, `src/skillsaw/formats/grok.py`, so a behavior change is an edit there rather
  than a hunt through rule code.
- Detection — `src/skillsaw/discovery/detect.py` (`grok-project`: any of `rules/`,
  `skills/`, `agents/`, `commands/`, `hooks/`, `workflows/`, `roles/`, `personas/`,
  `config.toml`, `lsp.json` or `sandbox.toml` inside a `.grok/` — eleven entries in
  `_TOOL_EVIDENCE["grok-project"]`); `RepositoryType.GROK_PROJECT` in
  `src/skillsaw/repository_types.py` is what the rule gates on and what `Repo type:`
  reports.
- Skills — `.grok/skills` in `CONVENTIONAL_SKILL_DIRS`
  (`src/skillsaw/discovery/__init__.py`), which is what earns the whole skill rule set
  without a Grok rule.
- Lint tree nodes — `src/skillsaw/blocks/json_config.py` (`GrokHooksBlock`, a
  `HooksBlock` subclass so `hooks-dangerous` and `hooks-prohibited` scan it like every
  other host's hooks file; lenient JSON on purpose, because Grok's `serde_json` reader
  accepts a duplicate key and runs the file), `src/skillsaw/blocks/content.py`
  (`GrokRuleBlock`), `src/skillsaw/blocks/frontmatter.py` (`GrokCommandBlock`,
  `GrokAgentBlock`) and `src/skillsaw/blocks/grok.py` (`GrokConfigBlock`, a direct
  `LintTarget` carrying `McpConfigRole` — never a `ContentBlock`, which would lint TOML
  as prose, and never a `JsonConfigBlock`, whose hierarchy parses JSON), attached in
  `src/skillsaw/lint_tree.py`.
- The Rust-dialect matcher check is shared with Muse Code:
  `rust_matcher_error` in `src/skillsaw/rules/builtin/utils.py`.

## Sync notes
Hand-copied values and measured facts that drift — re-check each against the shipped
user guide, or re-verify empirically with the canary matrix above:
- `HOOK_EVENTS` (the 15 above) in `formats/grok.py`.
- `HOOK_EVENT_ALIASES` — 39 entries. The irregular one is `userPromptSubmit`, which
  Grok does *not* accept although every other camelCase spelling loads; verify a new
  alias rather than deriving it from a naming rule.
- `HOOK_HANDLER_TYPES` = `{"command", "http"}` and `HOOK_REQUIRED_FIELDS`, the field
  each type needs.
- `HANDLER_FIELDS` (the typed table) and `RESERVED_ENV_VARS`.
- `MATCHER_IGNORED_EVENTS` = `{"Stop", "UserPromptSubmit"}`.
- `WILDCARD_MATCHERS` = `{"", "*"}` — `*` is special-cased by Grok, not compiled.
- `REQUIRED_FIELDS` = `("name", "description")` in `rules/builtin/grok/agent_valid.py` —
  the keys Grok's subagent loader requires; scalars, including empty/null values,
  register, while collections are rejected.
- `TIMEOUT_MAX` = `2**64 - 1` in `formats/grok.py`, the `u64` ceiling `timeout`
  deserializes into. It has to track Grok's timeout type: widen or narrow the field
  upstream and the boundary this reports moves with it.
- `PLUGIN_NAME_RE` = `\A[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?\Z`, read with `.fullmatch()`
  so a trailing newline is refused as the loader refuses it, and
  `PLUGIN_NAME_MAX_LENGTH` = 64 in `formats/grok.py`, measured boundary by boundary:
  `-lead`, `trail-`, `UPPER`, `under_score`, `dot.name`, `""` and 65 characters are
  rejected; `123`, `a`, `a--b` and 64 characters are accepted. The loader's own message
  is what `grok-plugin-json-valid` quotes.
- `SHA_RE` and `SHA_LENGTHS` = `{40, 64}` in `formats/grok.py` and
  `effective_install_pin` in `formats/grok_install.py`: typed catalog fields are
  checked at load; install pins are trimmed and matched case-insensitively. Explicit
  non-null `sha` wins, otherwise a full-commit `ref` supplies the pin. Ordinary refs
  stay unpinned. The upstream validator's narrower lowercase 40-hex policy gets INFO;
  display-index SHA comparison remains exact and does not use this normalization.
- **Duplicate resolved names are an install failure**, which is what makes the
  duplicate check in `grok-marketplace-json-valid` an ERROR. Re-verify by installing
  from a catalog with two entries resolving to one manifest name; the measured message
  is `Multiple marketplaces provide a plugin named "canary"`.
- `SINGLE_PATH_FIELDS` = `{"hooks", "mcpServers"}` in `formats/grok.py`: each takes one
  path or one inline JSON value. Measured, `"hooks": ["hooks/hooks.json"]` loaded as an
  empty inline document (`hookType: "inline"`, no target) where the bare string loaded
  the file, and `"mcpServers": ["servers.json"]` loaded no servers. Re-verify with
  `grok inspect --json` if the manifest type changes upstream.
- The component set that makes a manifest-less directory installable —
  `skills/`, `agents/`, `hooks/hooks.json`, `.mcp.json` — in `_installable` in
  `rules/builtin/grok/plugin_structure.py`. `_has_child_plugin` mirrors the
  installer's single-level fallback without following child symlinks. `commands/` alone and
  `.lsp.json` alone are discovered and then refused by `grok plugin install`, which is
  the asymmetry to re-verify if the installer changes.
- **Replace, not extend.** A manifest `skills`/`commands`/`agents` path replaces the
  conventional directory; the official `plugin_catalog.py` unions the two, so the two
  readers disagree and the binary is the one to follow. `COMPONENT_PATHS` in
  `formats/grok.py` records both, `grok-plugin-json-valid` warns on the loss, and
  the lint tree attaches both, so what an override drops is still linted.
  `grok-marketplace-index-parity` is the exception: it compares against a file the
  *generator* wrote, so it carries the union of both readings and reports drift only
  for a name neither produces.
- `PROJECT_CONFIG_TABLES` and its `_MEASURED` / `_REFUSED` companions,
  `MCP_SERVER_FIELDS` and `mcp_transport()` in
  `formats/grok.py`.
  The split between measured and documented is the thing to preserve: re-measure before
  moving a name across it, and never widen a rule's claim on the reference's word alone.
  `PROJECT_CONFIG_TABLES` is the allow-list `grok-config-project-scope` reports
  against, so a table added upstream reads as ignored until it is added here — which
  is what the rule's `extra-tables` option is for in the meantime. A "use this
  instead" hint needs both `_REFUSED` membership and an entry in the rule's
  `_REFUSED_HINTS`, which today holds `hooks` alone.
  `MCP_SERVER_FIELDS` came from the `mcp_servers.<name>.*` rows of
  `26-config-reference.md` and was confirmed accepted by watching for
  `mcpConfigProblems`; a field added upstream reads as unknown until it is added here.
  The decoder in `formats/grok_mcp.py` owns field types; `grok-config-valid`
  never reports membership, because an unknown field warns and the server still loads.
  `MCP_TYPE_MISSPELLED_FIELD` (`transport`) and `PERMISSION_MISSPELLED_KEY`
  (`defaultMode`) sit beside it: a spelling that would become real upstream must move
  out of the misspelling constants, not gain an exception in a rule.
- `rules/`, `commands/`, `agents/` and `hooks/` are read **flat**; `skills/` is walked
  recursively. Re-verify with `grok inspect --json` on a nested file. A change here is
  silent under-attachment — skillsaw stops linting real context and reports nothing —
  not a false positive, so nothing fails to draw attention to it.
- `.grok/settings.json` is **reserved**. superagent-ai/grok-cli is a second reader of a
  project `.grok/`, and its hooks loader names a project-level `settings.json` there
  only to skip it. Never attach it and never make it detection evidence — it is not a
  surface Grok Build reads, and claiming it would claim another tool's state.

## Not covered yet
Deliberate gaps, each with the reason it is a separate piece of work:
- **`.lsp.json`** — no public schema, and no LSP entries in the official marketplace, so
  there is nothing to calibrate a rule against.
- **`.grok/lsp.json`, `.grok/sandbox.toml`, `.grok/roles/`, `.grok/personas/`,
  `.grok/workflows/*.rhai`** — no public schema, subtle semantics, or a scripting
  language a regex would misread. Those five are detection evidence today and nothing
  more: nothing parses or attaches them, so detection and attachment cannot disagree
  about them. `config.toml` is the one that graduated — it is parsed and attached.

# Grok Build

<!-- Repo-root-relative src/... paths below are intentionally kept as prose, not navigable links. -->
<!-- skillsaw-disable content-unlinked-internal-reference -->

Grok Build is xAI's terminal coding agent. A checkout configures it through `.grok/`.
Most of that layer is shared convention other tools read too — portable Agent Skills,
Markdown prose, `AGENTS.md` — so the one thing skillsaw validates that is Grok's alone
is its lifecycle hooks.

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
  - *Whole file*: malformed JSON; a bare `NaN`/`Infinity`/`-Infinity`; no top-level
    `hooks` object, or one that is not an object; an event whose value is not an array;
    a matcher group that is not an object; a group with no `hooks` key or a non-array
    one; a handler that is not an object; a handler with no `type`; any known handler
    field carrying the wrong JSON type.
  - *That group*: a `matcher` string that does not compile.
  - *That event's entries*: a name outside the events and aliases below.
  - *That handler*: a `command` handler with no `command`, an `http` handler with no
    `url`, a `type` outside `command`/`http`.
- **Events** (15): `SessionStart`, `SessionEnd`, `UserPromptSubmit`, `PreToolUse`,
  `PostToolUse`, `PostToolUseFailure`, `PermissionDenied`, `Stop`, `StopFailure`,
  `StopCancelled`, `Notification`, `SubagentStart`, `SubagentStop`, `PreCompact`,
  `PostCompact`.
- **Aliases**, all normalized and all accepted — a missing one is a false "unknown
  event" on a working file: `SubagentEnd`; the `snake_case` spelling of all 16 names;
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
  any of them refuses the file; a key outside the table is tolerated.
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
  *skill*, which is why `grok inspect` lists it among the skills.
- **Trust gate**: hooks, MCP and LSP require folder trust (`/hooks-trust`, `--trust`,
  or `GROK_FOLDER_TRUST=0`); skills, rules, commands and agents load unconditionally.
  Trust is recorded in `~/.grok/trusted_folders.toml`, outside the repository, so it
  changes nothing about what skillsaw lints.
- **There is no `.grok/mcp.json`.** Grok's MCP sources are `config.toml`
  `[mcp_servers]`, `~/.claude.json`, `.cursor/mcp.json` and the repository-root
  `.mcp.json`. A `.grok/mcp.json` placed in a trusted project loaded nothing, and the
  file appears nowhere in the docs. Do not attach it.

## skillsaw rules that map
- Hooks — `src/skillsaw/rules/builtin/grok/`: `grok-hooks-valid`.
- Vocabulary (events, aliases, handler fields, reserved env, failure scopes) — one
  module, `src/skillsaw/formats/grok.py`, so a behavior change is an edit there rather
  than a hunt through rule code.
- Detection — `src/skillsaw/discovery/detect.py` (`grok-project`: any of `rules/`,
  `skills/`, `agents/`, `commands/`, `hooks/`, `config.toml` or `lsp.json` inside a
  `.grok/`); `RepositoryType.GROK_PROJECT` in `src/skillsaw/repository_types.py` is
  what the rule gates on and what `Repo type:` reports.
- Skills — `.grok/skills` in `CONVENTIONAL_SKILL_DIRS`
  (`src/skillsaw/discovery/__init__.py`), which is what earns the whole skill rule set
  without a Grok rule.
- Lint tree nodes — `src/skillsaw/blocks/json_config.py` (`GrokHooksBlock`, a
  `HooksBlock` subclass so `hooks-dangerous` and `hooks-prohibited` scan it like every
  other host's hooks file; lenient JSON on purpose, because Grok's `serde_json` reader
  accepts a duplicate key and runs the file), `src/skillsaw/blocks/content.py`
  (`GrokRuleBlock`) and `src/skillsaw/blocks/frontmatter.py` (`GrokCommandBlock`,
  `GrokAgentBlock`), attached in `src/skillsaw/lint_tree.py`.
- The Rust-dialect matcher check is shared with Muse Code:
  `rust_matcher_error` in `src/skillsaw/rules/builtin/utils.py`.

## Sync notes
Hand-copied value sets that drift — re-check each against the shipped user guide, or
re-verify empirically with the canary matrix above:
- `HOOK_EVENTS` (the 15 above) in `formats/grok.py`.
- `HOOK_EVENT_ALIASES` — 39 entries. The irregular one is `userPromptSubmit`, which
  Grok does *not* accept although every other camelCase spelling loads; verify a new
  alias rather than deriving it from a naming rule.
- `HOOK_HANDLER_TYPES` = `{"command", "http"}` and `HOOK_REQUIRED_FIELDS`, the field
  each type needs.
- `HANDLER_FIELDS` (the typed table) and `RESERVED_ENV_VARS`.
- `MATCHER_IGNORED_EVENTS` = `{"Stop", "UserPromptSubmit"}`.
- `WILDCARD_MATCHERS` = `{"", "*"}` — `*` is special-cased by Grok, not compiled.

## Not covered yet
Deliberate gaps, each with the reason it is a separate piece of work:
- **Plugins and the marketplace** — `.grok-plugin/plugin.json`, `.grok-plugin/
  marketplace.json` and `plugin-index.json`. A plugin directory carrying both
  `.grok-plugin/` and `.claude-plugin/` is valid to both tools, and Grok reads
  `.claude-plugin/plugin.json` as a fallback, so this is a provenance problem
  (`RepositoryContext.provenance()`) rather than a tool-directory one. Manifest
  resolution order is `plugin.json` > `.grok-plugin/plugin.json` >
  `.claude-plugin/plugin.json`.
- **`.grok/config.toml`** — only `[mcp_servers]`, `[plugins]`, `[permission]` and
  `[mcp] max_output_bytes` are honored at project scope and everything else is silently
  ignored, which is a high-signal check. It needs a TOML parser, and `tomllib` is
  stdlib only from Python 3.11 while this project supports 3.9, so it carries a new
  conditional `tomli` dependency that should be argued on its own.
- **`.grok/lsp.json`, `.grok/sandbox.toml`, `.grok/roles/`, `.grok/personas/`,
  `.grok/workflows/*.rhai`** — no public schema, a TOML dependency, or a scripting
  language a regex would misread. `lsp.json` and `config.toml` are detection evidence
  today and nothing more.

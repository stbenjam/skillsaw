# Muse Code

<!-- Repo-root-relative src/... paths below are intentionally kept as prose, not navigable links. -->
<!-- skillsaw-disable content-unlinked-internal-reference -->

Muse Code is Meta's terminal coding agent. Within a project repository, Muse Code
defines committed project hooks in `.muse/hooks.json`. Muse also reads shared
conventions including `AGENTS.md`, `.agents/skills`, and committed notes under
`.agents/memory/`, which are supported by skillsaw across multiple tools.

## Upstream source(s)
- https://dev.meta.ai/docs/muse-code/extending#hooks — hook sources, lifecycle events,
  load-time validation behavior.
- https://dev.meta.ai/docs/muse-code/configuration#local-memory — memory layout, the
  index, and the session-start injection cap.
- https://dev.meta.ai/docs/muse-code/configuration#agents-md — instruction file search
  order.

While upstream documentation lists lifecycle events and file locations, full configuration
examples are not yet published. The structure and failure scopes documented below were
carefully verified against Muse Code 1.0.2 (`1.0.2-R2040.1`) using a 73-case empirical
test matrix: testing one scenario per workspace with variations in `.muse/hooks.json`,
logging output via `muse exec --provider echo`. Because Muse runs hooks silently during
headless execution without printing error messages, `muse-hooks-valid` helps developers
catch issues early. Re-running the test matrix is recommended when updating these rules.

## What to check
- **Hooks file**: `<project-root>/.muse/hooks.json` — user hooks live in
  `~/.config/muse/settings.json` and managed hooks wherever `managed_hooks_path`
  points, neither in the repository.
- **Shape**: the nested form Claude Code defined —
  `{"hooks": {Event: [{matcher?, hooks: [handler, ...]}, ...]}}`. Top-level keys other
  than `hooks` are ignored; `hooks` must be an object.
- **Failure scopes** describe the exact impact of an invalid configuration:
  - *Whole file*: An event value that is not an array; a matcher group that is not an
    object; a non-string group `matcher`; a missing or non-array `hooks` list; a handler
    that is not an object; or any recognized handler field containing an unexpected JSON type.
  - *Matcher group*: A matcher group containing unsupported keys beyond `matcher` and
    `hooks`; or a `matcher` regular expression that fails to compile.
  - *Event entries*: An unrecognized or unsupported event name (case-sensitive).
  - *Individual handler*: A missing or unsupported `type`; a missing or empty `command`;
    providing only Windows commands without a fallback POSIX `command`; unknown handler
    keys; unsupported options like `if`, `condition`, `shell`, `rewakeMessage`, or
    `rewakeSummary`; or setting `once: true` or `asyncRewake: true`.
- **Events** (13 documented): `SessionStart`, `UserPromptSubmit`, `PreToolUse`,
  `PermissionRequest`, `PostToolUse`, `PreLLMCall`, `PostLLMCall`, `PreCompact`,
  `PostCompact`, `SubagentStart`, `SubagentStop`, `Stop`, `SessionEnd`. Four more —
  `Notification`, `PostToolUseFailure`, `StopFailure`, `PostToolBatch` — are in the
  binary's `HookEventKind` enum but not the documented list and could not be exercised
  headlessly, so skillsaw reports them at `info`. `Setup` is a Claude Code event the
  binary recognises and deliberately does not run ("Claude hook event `Setup` is
  recognized but is not run by Muse").
- **Handler type**: `command` only — Muse "binds a shell command to a lifecycle
  event." No `mcp_tool`, `prompt`, or `agent` handlers.
- **Handler fields Muse accepts**, with the JSON type each must carry: `type`,
  `command`, `commandWindows`, `command_windows`, `statusMessage`, `rewakeMessage`,
  `rewakeSummary`, `shell`, `condition`, `if` (all strings); `timeout` (non-negative
  int); `async`, `once`, `asyncRewake` (bool); `outputCapabilities` (list, members
  undocumented); `silent` (anything). A wrong type on any of them rejects the file; a
  key outside the table drops the handler.
- **Memory layout**: `<repo>/.agents/memory/` — a `MEMORY.md` index (one line per
  topic file by convention) alongside individual topic Markdown files. Muse loads
  `MEMORY.md` into context at session start and provides the paths of other topic files
  in the directory (up to 48 files) for on-demand reference.

  Committed project memory is a tool-agnostic open convention that provides version-controlled
  team memory across different AI coding tools. Because it is shared, skillsaw attaches
  the directory unconditionally and applies standard content and security rules.
- **Instruction file search order**: `AGENTS.md`, `CLAUDE.md`, `.agents/AGENTS.md`,
  `.claude/CLAUDE.md` — the first that exists wins for that directory level; a deeper
  level's file wins over a shallower one. Nothing Muse-specific is needed for this: the
  shared instruction-file discovery already attaches all four.

## skillsaw rules that map
- Hooks — `src/skillsaw/rules/builtin/muse/`: `muse-hooks-valid`.
- Vocabulary (events, handler fields, failure scopes) — one module,
  `src/skillsaw/formats/muse.py`, so a behavior change is an edit there rather than a
  hunt through rule code.
- Detection — `src/skillsaw/discovery/detect.py` (`HAS_MUSE`: a `.muse/hooks.json`,
  and nothing else); `src/skillsaw/context.py` exposes the format flag.
- Lint tree nodes — `src/skillsaw/blocks/json_config.py` (`MuseHooksBlock`, a
  `HooksBlock` subclass so `hooks-dangerous` and `hooks-prohibited` scan it like every
  other host's hooks file; lenient JSON on purpose, because Muse's `serde_json` reader
  accepts a duplicate key and runs the file) and `src/skillsaw/blocks/content.py`
  (`AgentMemoryIndexBlock`, `AgentMemoryBlock`, both in the `memory` budget category),
  attached in `src/skillsaw/lint_tree.py`. The shared memory vocabulary lives in
  `src/skillsaw/discovery/__init__.py`.

## Sync notes
Hand-copied value sets that drift — re-check each against the docs, or re-verify
empirically if the docs still omit an example:
- `HOOK_EVENTS` (13 documented events, above) in `formats/muse.py`.
- `UNDOCUMENTED_HOOK_EVENTS` and `RECOGNIZED_UNRUN_EVENTS` — the enum names and the
  `Setup` diagnostic, both read out of the binary rather than the docs.
- `HOOK_HANDLER_TYPES` = `{"command"}`.
- `MATCHER_GROUP_FIELDS` = `{"matcher", "hooks"}` — any other key at that level drops
  the group.
- `HANDLER_FIELDS` (typed fields table), `UNSUPPORTED_HANDLER_FIELDS` (recognized but
  unsupported string fields), and `UNSUPPORTED_WHEN_TRUE` (`once`, `asyncRewake`) in
  `formats/muse.py`. Fields that Muse parses and explicitly rejects are distinguished
  from entirely unrecognized keys to provide helpful, specific guidance.
- The memory listing cap (48 Markdown files) is a documented Muse behavior with no
  constant of its own; it is recorded here rather than in code because no rule reads
  it.

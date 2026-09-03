# Muse Code

<!-- Repo-root-relative src/... paths below are intentionally kept as prose, not navigable links. -->
<!-- skillsaw-disable content-unlinked-internal-reference -->

Muse Code is Meta's terminal coding agent. skillsaw lints two things it reads from a
checkout: committed project hooks and committed project memory.

## Upstream source(s)
- https://dev.meta.ai/docs/muse-code/extending#hooks — hook sources, lifecycle events,
  load-time validation behavior.
- https://dev.meta.ai/docs/muse-code/configuration#local-memory — memory layout, the
  index, and the session-start injection cap.
- https://dev.meta.ai/docs/muse-code/configuration#agents-md — instruction file search
  order.

The docs name the events and the file locations but publish no example of a hooks
file, so the shape and the field rules below were verified against Muse Code 1.0.2
(`1.0.2-R2040.1`) by running `muse exec --provider echo` in scratch workspaces whose
`.muse/hooks.json` carried one variation each, with every handler writing a token to a
log file. The loader emits no diagnostic in headless runs — a rejected handler, group,
or file simply never fires — which is why `muse-hooks-valid` exists. Re-run that matrix
before changing a rule here.

## What to check
- **Hooks file**: `<project-root>/.muse/hooks.json` — user hooks live in
  `~/.config/muse/settings.json` and managed hooks wherever `managed_hooks_path`
  points, neither in the repository.
- **Shape**: the nested form Claude Code defined —
  `{"hooks": {Event: [{matcher?, hooks: [handler, ...]}, ...]}}`. Failure scope differs
  by level: an unknown event name skips only that event's entries; a malformed matcher
  group (not an object, a non-string `matcher`, a missing/non-array `hooks`, or any
  field other than `matcher`/`hooks`) rejects the whole file; a malformed handler
  (missing/unknown `type`, empty/non-string `command`, an unrecognized field, or a
  wrong-typed known field) drops only that handler.
- **Events** (13): `SessionStart`, `UserPromptSubmit`, `PreToolUse`,
  `PermissionRequest`, `PostToolUse`, `PreLLMCall`, `PostLLMCall`, `PreCompact`,
  `PostCompact`, `SubagentStart`, `SubagentStop`, `Stop`, `SessionEnd`. Names are
  case-sensitive; `SessionEnd` is observational only (its output cannot block, inject
  context, or stop the session).
- **Handler type**: `command` only — Muse "binds a shell command to a lifecycle
  event." No `mcp_tool`, `prompt`, or `agent` handlers.
- **Handler fields Muse accepts**: `type`, `command`, `commandWindows` /
  `command_windows`, `timeout` (non-negative int), `statusMessage`, `async`, `silent`,
  `outputCapabilities`. Any other field drops the handler — including Claude-only
  fields such as `args`, `env`, `description`, `once`, `if`, and `shell`.
- **Memory layout**: `<repo>/.agents/memory/` — a `MEMORY.md` index (one line per
  topic file) plus one Markdown file per topic. Muse injects `MEMORY.md` in full at
  every session start, even in an untrusted workspace — the docs themselves flag this
  as a prompt-injection surface — and lists up to 48 topic-file paths from the index;
  beyond that cap a topic file is never surfaced.
- **Instruction file search order**: `AGENTS.md`, `CLAUDE.md`, `.agents/AGENTS.md`,
  `.claude/CLAUDE.md` — the first that exists wins for that directory level; a deeper
  level's file wins over a shallower one.

## skillsaw rules that map
- Hooks — `src/skillsaw/rules/builtin/muse/`: `muse-hooks-valid`.
- Vocabulary (events, handler fields, memory cap, search order) — one module,
  `src/skillsaw/formats/muse.py`, so a behavior change is an edit there rather than a
  hunt through rule code.
- Detection — `src/skillsaw/discovery/detect.py` (`HAS_MUSE`: a `.muse/hooks.json` or
  an `.agents/memory/` directory); `src/skillsaw/context.py` exposes the format flag.
- Lint tree nodes — `src/skillsaw/blocks/json_config.py` (`MuseHooksBlock`, a
  `HooksBlock` subclass so `hooks-dangerous` and `hooks-prohibited` scan it like every
  other host's hooks file) and `src/skillsaw/blocks/content.py` (`MuseMemoryIndexBlock`
  for `MEMORY.md`, budgeted as always-on instruction text; `MuseMemoryBlock` for topic
  files, budgeted as on-demand prose), attached in `src/skillsaw/lint_tree.py`.

## Sync notes
Hand-copied value sets that drift — re-check each against the docs, or re-verify
empirically if the docs still omit an example:
- `HOOK_EVENTS` (13 events, above) in `formats/muse.py`.
- `HOOK_HANDLER_TYPES` = `{"command"}`.
- `MATCHER_GROUP_FIELDS` = `{"matcher", "hooks"}` — any other key at that level
  rejects the whole file.
- `HANDLER_FIELDS` and `UNSUPPORTED_HANDLER_FIELDS` in `formats/muse.py`: fields Muse
  parses and then rejects the handler for (`if`, `condition`, `shell`, `once`,
  `asyncRewake`, `rewakeMessage`, `rewakeSummary`) are distinct from fields it never
  recognizes at all — both drop the handler, but the diagnostic differs.
- `MEMORY_INDEX_FILE_LIMIT` = 48.
- `INSTRUCTION_SEARCH_ORDER`, above.

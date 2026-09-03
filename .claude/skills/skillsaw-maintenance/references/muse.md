# Muse Code

<!-- Repo-root-relative src/... paths below are intentionally kept as prose, not navigable links. -->
<!-- skillsaw-disable content-unlinked-internal-reference -->

Muse Code is Meta's terminal coding agent. The one thing skillsaw lints that is Muse's
alone is committed project hooks. Muse also reads `AGENTS.md`, `.agents/skills` and the
committed `.agents/memory/` notes, but those are shared conventions other tools read
too — see the memory section below.

## Upstream source(s)
- https://dev.meta.ai/docs/muse-code/extending#hooks — hook sources, lifecycle events,
  load-time validation behavior.
- https://dev.meta.ai/docs/muse-code/configuration#local-memory — memory layout, the
  index, and the session-start injection cap.
- https://dev.meta.ai/docs/muse-code/configuration#agents-md — instruction file search
  order.

The docs name the events and the file locations but publish no example of a hooks
file, so the shape and the failure scopes below were verified against Muse Code 1.0.2
(`1.0.2-R2040.1`) with a 73-case canary matrix: one scratch workspace per case, each
`.muse/hooks.json` carrying a single variation, every handler writing a token to a log
file, run under `muse exec --provider echo`. The loader emits no diagnostic in headless
runs — a rejected file, group, event or handler simply never fires — which is why
`muse-hooks-valid` exists. Re-run that matrix before changing a rule here.

## What to check
- **Hooks file**: `<project-root>/.muse/hooks.json` — user hooks live in
  `~/.config/muse/settings.json` and managed hooks wherever `managed_hooks_path`
  points, neither in the repository.
- **Shape**: the nested form Claude Code defined —
  `{"hooks": {Event: [{matcher?, hooks: [handler, ...]}, ...]}}`. Top-level keys other
  than `hooks` are ignored; `hooks` must be an object.
- **Failure scope** is the thing to get right, because it is what the diagnostic is
  worth:
  - *Whole file*: an event whose value is not an array; a matcher group that is not an
    object; a non-string group `matcher`; a group with no `hooks` key or a non-array
    one; a handler that is not an object; any known handler field carrying the wrong
    JSON type.
  - *That group*: a group carrying any key outside `matcher`/`hooks`, whatever its
    value; a `matcher` string that does not compile.
  - *That event's entries*: an event name Muse does not dispatch (case-sensitive).
  - *That handler*: missing `type`; an unknown `type` string; `command` missing, empty
    or whitespace; only `commandWindows`/`command_windows`; a key Muse does not know;
    `if`/`condition`/`shell`/`rewakeMessage`/`rewakeSummary` with a string value;
    `once: true` or `asyncRewake: true`. `once: false`, `asyncRewake: false` and
    `silent` with any value are accepted silently.
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
  topic file, by convention) plus one Markdown file per topic. Muse injects
  `MEMORY.md` in full at every session start, even in an untrusted workspace — the
  docs themselves flag this as a prompt-injection surface — and lists the paths of
  the other Markdown files in the directory, whether or not the index mentions them,
  up to 48; beyond that cap a file is never surfaced. **This is not Muse's
  convention.**
  Projects were committing `.agents/memory/` before Muse Code shipped, describing it as
  tool-agnostic team memory complementing Claude Code's per-developer auto memory, and
  Muse adopted it the way it adopted `AGENTS.md`. skillsaw treats it as shared:
  unconditionally attached, evidence of no tool.
- **Instruction file search order**: `AGENTS.md`, `CLAUDE.md`, `.agents/AGENTS.md`,
  `.claude/CLAUDE.md` — the first that exists wins for that directory level; a deeper
  level's file wins over a shallower one. Nothing Muse-specific is needed for this: the
  shared instruction-file discovery already attaches all four.

## skillsaw rules that map
- Hooks — `src/skillsaw/rules/builtin/muse/`: `muse-hooks-valid`.
- Vocabulary (events, handler fields, failure scopes) — one module,
  `src/skillsaw/formats/muse.py`, so a behavior change is an edit there rather than a
  hunt through rule code.
- Detection — `src/skillsaw/discovery/detect.py` (`muse`: a `.muse/hooks.json`,
  and nothing else); `RepositoryType.MUSE` in `src/skillsaw/repository_types.py`
  is what the rule gates on and what `Repo type:` reports.
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
- `HANDLER_FIELDS` (the typed table), `UNSUPPORTED_HANDLER_FIELDS` (present with a
  string value) and `UNSUPPORTED_WHEN_TRUE` (`once`, `asyncRewake`) in
  `formats/muse.py`. Fields Muse parses and then refuses the handler for are distinct
  from fields it never recognizes at all — both drop the handler, but the diagnostic
  differs.
- The memory listing cap (48 Markdown files) is a documented Muse behavior with no
  constant of its own; it is recorded here rather than in code because no rule reads
  it.

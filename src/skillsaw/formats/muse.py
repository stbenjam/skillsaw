"""Muse Code repository-context vocabulary, in one place.

Muse Code is Meta's terminal coding agent. It reads two things skillsaw
lints from a checkout of its own — project hooks in ``.muse/hooks.json`` —
plus the shared conventions other rules already cover: ``AGENTS.md``,
``.agents/skills``, and the committed ``.agents/memory/`` notes whose
vocabulary lives in :mod:`skillsaw.discovery`, not here, because no tool
owns it. The Muse-specific facts live in this module so a change in Muse's
behavior is an edit to this file rather than a hunt through rule code.

Sources:

* https://dev.meta.ai/docs/muse-code/extending#hooks — hook sources,
  lifecycle events, load-time validation behavior (read 2026-09-02).
* https://dev.meta.ai/docs/muse-code/configuration#local-memory — memory
  layout, the index, and the session-start injection cap.

Muse's docs name the events and the file locations but publish no example
of a hooks file, so the shape and the failure scopes below were verified
against Muse Code 1.0.2 (``1.0.2-R2040.1``) with a 73-case canary matrix:
one scratch workspace per case, each ``.muse/hooks.json`` carrying a single
variation, every handler writing a token to a log file, run under ``muse
exec --provider echo``. The log says what fired. The loader emits no
diagnostic in a headless run: a rejected file, a rejected group and a
dropped handler all look like a hook that had nothing to do. Re-run that
matrix before changing a rule here.

What it showed. The file is the nested shape Claude Code defined:
``{"hooks": {Event: [{matcher?, hooks: [handler, ...]}, ...]}}``. Top-level
keys other than ``hooks`` are ignored, and ``hooks`` must be an object.
Failure scope then differs by level, and the scope is what makes a defect
worth reporting — a whole-file rejection costs every hook in the file:

* **Whole file** — an event whose value is not an array; a matcher group
  that is not an object; a group ``matcher`` that is not a string; a group
  with no ``hooks`` key or a non-array one; a handler that is not an
  object; any known handler field carrying the wrong JSON type
  (:data:`HANDLER_FIELDS`); a bare ``NaN``, ``Infinity`` or ``-Infinity``
  token anywhere in the document, including somewhere nothing is typed
  (``silent``, a member of ``outputCapabilities``). Those three are not
  JSON and ``serde_json`` refuses the document for them, while Python's
  ``json`` accepts them as floats — so skillsaw scans for them rather than
  inheriting a verdict from its parser.
* **That matcher group** — a group carrying any key outside ``matcher``
  and ``hooks``, whatever its value; a ``matcher`` string that does not
  compile as a regex. Sibling groups and other events still load.
* **That event's entries** — an event name Muse does not dispatch. Names
  are case-sensitive, so ``sessionStart`` is one. The rest of the file
  loads.
* **That handler** — a missing ``type`` or an unknown one; a ``command``
  that is missing, empty, or whitespace; a field Muse does not know; a
  field in :data:`UNSUPPORTED_HANDLER_FIELDS` present with a string value;
  a field in :data:`UNSUPPORTED_WHEN_TRUE` set to ``true``. Sibling
  handlers in the same group still run.

``matcher`` is a regex applied on every event (a non-matching pattern on
``Stop`` or ``UserPromptSubmit`` suppresses the hook); omitted, empty, and
``"*"`` all match everything. Muse compiles it with Rust's ``regex``
crate, whose dialect is a superset of Python's in places.
"""

from __future__ import annotations

from typing import Any, Mapping

#: The project directory Muse Code reads. Only ``hooks.json`` inside it is
#: committed configuration.
TOOL_DIR_NAME = ".muse"

#: Subdirectories of :data:`TOOL_DIR_NAME` that hold Muse's own scratch,
#: not configuration. ``worktrees/`` is where Muse checks out a git worktree
#: per child agent — a full copy of the repository that Muse adds to
#: ``.git/info/exclude`` — so a walk that descended into it would lint
#: every file twice.
SCRATCH_DIR_NAMES = frozenset({"worktrees"})

#: Project hooks, relative to :data:`TOOL_DIR_NAME`. User hooks live in
#: ``~/.config/muse/settings.json`` and managed hooks wherever
#: ``managed_hooks_path`` points — neither is in the repository.
HOOKS_FILENAME = "hooks.json"

#: Lifecycle events Muse Code documents, all 13 of them. A hook binds to
#: exactly one; an unknown name is an entry that never fires.
HOOK_EVENTS = frozenset(
    {
        "SessionStart",
        "UserPromptSubmit",
        "PreToolUse",
        "PermissionRequest",
        "PostToolUse",
        "PreLLMCall",
        "PostLLMCall",
        "PreCompact",
        "PostCompact",
        "SubagentStart",
        "SubagentStop",
        "Stop",
        "SessionEnd",
    }
)

#: Names present in the binary's ``HookEventKind`` enum but absent from
#: Muse's documented list, and not exercisable headlessly by the canary
#: matrix. Muse parses an entry under one of these rather than skipping it,
#: but whether anything dispatches it is unknown — so a rule says "verify",
#: not "this never fires".
UNDOCUMENTED_HOOK_EVENTS = frozenset(
    {
        "Notification",
        "PostToolUseFailure",
        "StopFailure",
        "PostToolBatch",
    }
)

#: Claude Code events Muse recognises by name and deliberately does not
#: run. The binary carries the diagnostic "Claude hook event `Setup` is
#: recognized but is not run by Muse", so a file shared with Claude Code
#: trips this rather than the unknown-event path.
RECOGNIZED_UNRUN_EVENTS = frozenset({"Setup"})

#: Handler types Muse runs. A hook "binds a shell command to a lifecycle
#: event": ``http``, ``prompt``, ``agent`` and ``mcp_tool`` handlers are
#: dropped. The value is case-sensitive.
HOOK_HANDLER_TYPES = frozenset({"command"})

#: The only keys a matcher group may carry. Any other key — Claude's
#: ``description``, Cursor's ``enabled`` — drops the group.
MATCHER_GROUP_FIELDS = frozenset({"matcher", "hooks"})

#: The JSON type Muse accepts for each handler field it knows. A wrong type
#: here rejects the whole file, so this table is the whole-file check;
#: presence rules are elsewhere. ``timeout`` is additionally a non-negative
#: integer — a float, a numeric string, a negative, a bool and ``null`` all
#: reject the file, while a huge integer is accepted. ``silent`` is read and
#: ignored whatever its value. ``outputCapabilities`` must be a list; its
#: accepted member values are undocumented, so members are never judged.
HANDLER_FIELDS: Mapping[str, Any] = {
    "type": str,
    "command": str,
    "commandWindows": str,
    "command_windows": str,
    "statusMessage": str,
    "rewakeMessage": str,
    "rewakeSummary": str,
    "shell": str,
    "condition": str,
    "if": str,
    "timeout": int,
    "async": bool,
    "once": bool,
    "asyncRewake": bool,
    "outputCapabilities": list,
    "silent": object,
}

#: Fields Muse parses and then drops the handler for whenever they carry a
#: string. ``if``/``condition`` because Muse cannot prove a condition;
#: ``shell`` because there is no per-handler shell selector;
#: ``rewakeMessage``/``rewakeSummary`` because reawakening handlers are
#: unsupported. All are Claude Code fields, so a shared file trips them.
UNSUPPORTED_HANDLER_FIELDS = frozenset(
    {
        "if",
        "condition",
        "shell",
        "rewakeMessage",
        "rewakeSummary",
    }
)

#: Boolean fields Muse drops the handler for when they are ``true``:
#: one-shot and reawakening handlers are unsupported. ``false`` is accepted
#: silently, which is why these are not in
#: :data:`UNSUPPORTED_HANDLER_FIELDS`.
UNSUPPORTED_WHEN_TRUE = frozenset({"once", "asyncRewake"})

#: Claude Code handler fields Muse knows nothing about. Listed only so the
#: diagnostic can say "Claude Code field" rather than only "unknown" for the
#: common cases; any key outside :data:`HANDLER_FIELDS` gets the same
#: verdict.
CLAUDE_ONLY_HANDLER_FIELDS = frozenset(
    {
        "args",
        "env",
        "description",
        "url",
        "headers",
        "allowedEnvVars",
        "server",
        "tool",
        "input",
        "prompt",
        "model",
    }
)

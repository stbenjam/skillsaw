"""Muse Code repository-context vocabulary, in one place.

Muse Code is Meta's terminal coding agent. It reads three things skillsaw
lints from a checkout: project hooks, project memory, and the shared
``AGENTS.md`` / ``.agents/skills`` conventions that other rules already
cover. The tool-specific facts live here so a change in Muse's behavior is
an edit to this file rather than a hunt through rule code.

Sources:

* https://dev.meta.ai/docs/muse-code/extending#hooks — hook sources,
  lifecycle events, load-time validation behavior (read 2026-09-02).
* https://dev.meta.ai/docs/muse-code/configuration#local-memory — memory
  layout, the index, and the session-start injection cap.
* https://dev.meta.ai/docs/muse-code/configuration#agents-md — instruction
  file search order.

Muse's docs name the events and the file locations but publish no example
of a hooks file, so the shape and the field rules below were verified
against Muse Code 1.0.2 (``1.0.2-R2040.1``) by running ``muse exec
--provider echo`` in scratch workspaces whose ``.muse/hooks.json`` carried
one variation each, with every handler writing a token to a log file. The
loader emits no diagnostic in headless runs: a rejected handler, group, or
file simply never fires. Re-run that matrix before changing a rule here.

What it showed. The file is the nested shape Claude Code defined:
``{"hooks": {Event: [{matcher?, hooks: [handler, ...]}, ...]}}``. Failure
scope differs by level:

* An unknown **event name** skips that event's entries; the rest of the
  file loads. Names are case-sensitive.
* A malformed **matcher group** — not an object, a non-string ``matcher``,
  a missing or non-array ``hooks``, or any field other than ``matcher`` and
  ``hooks`` — rejects the **whole file**. So does an event whose value is
  not an array.
* A malformed **handler** — missing or unknown ``type``, empty or non-string
  ``command``, a field Muse does not know, or a wrong-typed known field —
  drops that handler only; siblings still run.
* Top-level keys other than ``hooks`` are ignored; ``hooks`` must be an
  object.
* ``matcher`` is a regex applied on every event (a non-matching pattern on
  ``Stop`` or ``UserPromptSubmit`` suppresses the hook); omitted, empty, and
  ``"*"`` all match everything.
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

#: Committed project memory, relative to the repository root. Personal
#: project memory and machine-wide memory live outside the checkout.
MEMORY_DIR = (".agents", "memory")

#: The memory index: one line per topic file. Muse injects this file in
#: full at session start, even in an untrusted workspace.
MEMORY_INDEX_FILENAME = "MEMORY.md"

#: How many memory files Muse lists at session start. Beyond this, a topic
#: file is never surfaced to the agent.
MEMORY_INDEX_FILE_LIMIT = 48

#: Lifecycle events Muse Code dispatches hooks on, per the docs. A hook
#: binds to exactly one; an unknown name is an entry that never fires.
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

#: Events whose hooks are observational: output cannot block, inject
#: context, or stop the session.
OBSERVATIONAL_EVENTS = frozenset({"SessionEnd"})

#: Handler types Muse runs. A hook "binds a shell command to a lifecycle
#: event": ``http``, ``prompt``, ``agent`` and ``mcp_tool`` handlers are
#: dropped. The value is case-sensitive.
HOOK_HANDLER_TYPES = frozenset({"command"})

#: The only keys a matcher group may carry. Any other key — Claude's
#: ``description``, Cursor's ``enabled`` — rejects the whole file.
MATCHER_GROUP_FIELDS = frozenset({"matcher", "hooks"})

#: Handler fields Muse accepts, with the JSON types it accepts them as. A
#: handler carrying any key outside this table (and outside
#: :data:`UNSUPPORTED_HANDLER_FIELDS`) is dropped. ``timeout`` is a
#: non-negative integer — a float or a numeric string drops the handler.
#: ``silent`` is read and ignored whatever its value. ``outputCapabilities``
#: is parsed but its accepted values are undocumented, so it is not
#: type-checked here.
HANDLER_FIELDS: Mapping[str, Any] = {
    "type": str,
    "command": str,
    "commandWindows": str,
    "command_windows": str,
    "timeout": int,
    "statusMessage": str,
    "async": bool,
    "silent": object,
    "outputCapabilities": object,
}

#: Fields Muse parses and then rejects the handler for: the handler never
#: runs. ``if``/``condition`` because Muse cannot prove a condition;
#: ``shell`` because there is no per-handler shell selector; ``once`` and
#: the ``asyncRewake`` family because one-shot and reawakening handlers are
#: unsupported. All are Claude Code fields, so a shared file trips them.
UNSUPPORTED_HANDLER_FIELDS = frozenset(
    {
        "if",
        "condition",
        "shell",
        "once",
        "asyncRewake",
        "rewakeMessage",
        "rewakeSummary",
    }
)

#: Claude Code handler fields Muse knows nothing about. Listed only so the
#: diagnostic can say "Claude-only" rather than "unknown" for the common
#: cases; any key outside :data:`HANDLER_FIELDS` gets the same verdict.
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

#: Instruction files, in the order Muse checks each directory level; the
#: first that exists wins for that level.
INSTRUCTION_SEARCH_ORDER = ("AGENTS.md", "CLAUDE.md", ".agents/AGENTS.md", ".claude/CLAUDE.md")

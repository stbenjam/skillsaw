r"""Vocabulary and configuration constants for Muse Code.

Muse Code is Meta's terminal coding assistant. Within a repository checkout,
Muse Code defines project lifecycle hooks in ``.muse/hooks.json``. It also
supports shared conventions that skillsaw inspects across tools: ``AGENTS.md``,
``.agents/skills``, and committed team memory in ``.agents/memory/`` (the
constants for which live in :mod:`skillsaw.discovery` as they are shared
across multiple AI tools).

Consolidating Muse-specific constants and schemas into this module keeps
lifecycle rules organized and easy to maintain.

Upstream documentation and sources:
* https://dev.meta.ai/docs/muse-code/extending#hooks — hook sources,
  lifecycle events, and load-time validation behavior.
* https://dev.meta.ai/docs/muse-code/configuration#local-memory — memory
  layout, index structure, and session-start context limits.

Because upstream documentation provides event lists without complete JSON
examples, the configuration format and validation rules were empirically
verified against Muse Code 1.0.2 (``1.0.2-R2040.1``) across a comprehensive
test matrix. Since Muse runs hooks quietly during headless workflows without
printing error output, validation rules help developers identify and resolve
configuration issues up front.

Validation findings are grouped by scope to help pinpoint the exact impact:

* **Whole file** — The entire file is skipped if the top-level structure is
  invalid (e.g. an event value is not an array, a matcher group is not an object,
  a matcher regex is not a string, the ``hooks`` list is missing or non-array,
  or a handler field has an unexpected JSON type). Bare ``NaN`` or ``Infinity``
  tokens also cause the whole file to be rejected.
* **Matcher group** — A specific matcher group is skipped if it includes
  unsupported keys beyond ``matcher`` and ``hooks``, or if its ``matcher``
  regex fails to compile. Other matcher groups and events continue to load.
* **Event entries** — Handlers under an unrecognized event name are skipped.
  Event names are case-sensitive (for example, ``SessionStart`` is supported,
  while ``sessionStart`` is unrecognized).
* **Individual handler** — A single handler is skipped if it is missing a
  required ``type`` or ``command``, specifies only Windows commands without a
  fallback, includes unsupported options like ``if`` or ``shell``, or enables
  unsupported features like ``once: true``. Sibling handlers within the same
  group continue to run normally.

The ``matcher`` field compiles as a regular expression evaluated across events.
Muse compiles matchers using Rust's ``regex`` engine (which supports Unicode
character classes like ``\p{L}`` and character class operators, while omitting
backreferences and lookaround assertions).
"""

from __future__ import annotations

from typing import Any, Mapping

#: The project directory Muse Code reads for committed configuration.
TOOL_DIR_NAME = ".muse"

#: Subdirectories of :data:`TOOL_DIR_NAME` used for internal state rather than
#: configuration (such as git worktrees checked out for subagents).
SCRATCH_DIR_NAMES = frozenset({"worktrees"})

#: Project hooks configuration filename inside :data:`TOOL_DIR_NAME`. User
#: hooks live in ``~/.config/muse/settings.json``.
HOOKS_FILENAME = "hooks.json"

#: Documented lifecycle events supported by Muse Code. Each hook binds to
#: one event.
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

#: Additional event kinds present in Muse Code's internal enum but omitted from
#: official documentation.
UNDOCUMENTED_HOOK_EVENTS = frozenset(
    {
        "Notification",
        "PostToolUseFailure",
        "StopFailure",
        "PostToolBatch",
    }
)

#: Claude Code events that Muse Code recognizes by name but does not run
#: (such as ``Setup``).
RECOGNIZED_UNRUN_EVENTS = frozenset({"Setup"})

#: Handler types supported by Muse Code. Currently, Muse Code executes command hooks.
HOOK_HANDLER_TYPES = frozenset({"command"})

#: Allowed keys within a matcher group (``matcher`` and ``hooks``).
MATCHER_GROUP_FIELDS = frozenset({"matcher", "hooks"})

#: Expected JSON types for recognized handler fields. A type mismatch in these
#: fields causes Muse to reject the file.
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

#: Handler fields recognized by Muse but not currently supported during execution.
UNSUPPORTED_HANDLER_FIELDS = frozenset(
    {
        "if",
        "condition",
        "shell",
        "rewakeMessage",
        "rewakeSummary",
    }
)

#: Boolean options that are currently unsupported when set to ``true``
#: (such as ``once`` and ``asyncRewake``).
UNSUPPORTED_WHEN_TRUE = frozenset({"once", "asyncRewake"})

#: Claude Code handler fields recognized to provide clear, helpful diagnostics
#: when migrating configurations.
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

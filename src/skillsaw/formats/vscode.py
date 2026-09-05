"""VS Code's embedded agent hook vocabulary.

Pinned to VS Code 1.136.1: hookTypes.ts and hookSchema.ts. The loader falls
back to canonical event names beyond the target-specific editor suggestions.
"""

VSCODE_HOOK_COMMAND_FIELDS = ("command", "windows", "linux", "osx", "bash", "powershell")
VSCODE_HOOK_EVENTS = frozenset(
    {
        "SessionStart",
        "SessionEnd",
        "UserPromptSubmit",
        "PreToolUse",
        "PostToolUse",
        "PreCompact",
        "SubagentStart",
        "SubagentStop",
        "Stop",
        "ErrorOccurred",
    }
)
VSCODE_HOOK_TYPES = frozenset({"command"})

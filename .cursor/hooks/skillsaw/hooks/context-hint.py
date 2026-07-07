#!/usr/bin/env python3
"""Hint-only PostToolUse hook: nudge the agent to lint agentic context.

Reads the PostToolUse payload from stdin, and when the edited file is
agentic context (a skill, command, agent, hook, plugin manifest, or
instruction file), emits `additionalContext` reminding the agent to run
the skillsaw-lint skill on it.

Deliberately does NOT run the linter or anything else: no subprocesses,
no network, no reads outside stdin. Any unexpected input exits 0 silently
so the hook can never block a tool call.
"""

import json
import sys
from pathlib import PurePosixPath

# Basenames that are agentic context wherever they live.
_BASENAMES = {
    "SKILL.md",
    "CLAUDE.md",
    "AGENTS.md",
    "GEMINI.md",
    "hooks.json",
    "hooks.md",
    "plugin.json",
    "marketplace.json",
    ".clinerules",
    "copilot-instructions.md",
}

# Directory parts that mark everything under them as agentic context.
_DIR_MARKERS = [
    (".claude", "commands"),
    (".claude", "agents"),
    (".claude", "rules"),
    (".cursor", "rules"),
    (".kiro", "steering"),
    (".clinerules",),
    ("commands",),  # plugin commands/ dir
    ("agents",),  # plugin agents/ dir
]


def _is_agent_context(path_str: str) -> bool:
    path = PurePosixPath(path_str.replace("\\", "/"))
    if path.name in _BASENAMES:
        return True
    parts = path.parts
    for marker in _DIR_MARKERS:
        n = len(marker)
        for i in range(len(parts) - n):  # marker must be a directory, not the leaf
            if parts[i : i + n] == marker:
                # Restrict bare commands/ and agents/ matches to markdown files
                # so generic source trees don't trigger the hint.
                if marker in (("commands",), ("agents",)) and path.suffix != ".md":
                    break
                return True
    return False


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return
    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path") or ""
    if not isinstance(file_path, str) or not file_path:
        return
    if not _is_agent_context(file_path):
        return
    hint = (
        f"You just edited agentic context ({file_path}). Use the "
        "skillsaw-lint skill to lint and improve it before finishing: "
        f"`skillsaw lint {file_path}` (or `uvx skillsaw lint ...` if "
        "skillsaw is not installed)."
    )
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": hint,
                }
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:  # never block the tool call
        pass
    sys.exit(0)

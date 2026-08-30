"""Devin CLI and Devin Desktop repository-context vocabulary.

Devin rules read both their preferred ``.devin`` directory and the legacy
``.windsurf`` spelling. Windsurf's current ``.windsurf/skills`` format is a
portable Agent Skill, while Devin's ``.devin/skills`` format remains a native
dialect. Keep that boundary explicit so discovery can share locations without
making the two skill schemas interchangeable.

Sources:

* https://docs.devin.ai/cli/extensibility/rules
* https://docs.devin.ai/cli/extensibility/skills/creating-skills
* https://docs.devin.ai/desktop/cascade/memories
* https://docs.devin.ai/desktop/cascade/agents-md
"""

from __future__ import annotations

from pathlib import Path

# Preferred spelling first so tree attachment and diagnostics remain
# deterministic when a repository carries both forms.
TOOL_DIR_NAMES = (".devin", ".windsurf")
DEVIN_SKILL_DIR_NAME = ".devin"

# The CLI documents these exact spellings.  Desktop additionally treats
# AGENTS.md case-insensitively, handled by ``is_instruction_filename``.
INSTRUCTION_FILENAMES = frozenset(
    {
        "AGENTS.md",
        "AGENTS.local.md",
        "AGENT.md",
        ".windsurfrules",
        "CLAUDE.md",
    }
)

# Names that are positive Devin evidence by themselves.  AGENTS.md and
# CLAUDE.md are portable/Claude evidence too, so they do not claim Devin on
# their own; their nested copies are still attached and linted.
DEVIN_ONLY_INSTRUCTION_FILENAMES = frozenset({"AGENTS.local.md", "AGENT.md", ".windsurfrules"})

RULE_TRIGGERS = frozenset({"always_on", "manual", "model_decision", "agent", "glob"})
SKILL_TRIGGERS = frozenset({"user", "model"})
PERMISSION_KEYS = ("allow", "deny", "ask")
WORKSPACE_RULE_MAX_CHARACTERS = 12_000


def is_instruction_filename(name: str) -> bool:
    """Whether *name* is one of Devin's repository instruction files."""
    return name in INSTRUCTION_FILENAMES or name.lower() == "agents.md"


def is_devin_only_instruction_filename(name: str) -> bool:
    """Whether *name* identifies Devin rather than a portable format."""
    return name in DEVIN_ONLY_INSTRUCTION_FILENAMES or (
        name.lower() == "agents.md" and name != "AGENTS.md"
    )


def is_devin_native_skill_dir(path: Path) -> bool:
    """Whether *path* descends from a Devin-native skill collection."""
    for parent in path.parents:
        if parent.name == "skills" and parent.parent.name in TOOL_DIR_NAMES:
            # Parents are nearest-first. A nested collection belongs to its
            # closest declared tool root, not an unrelated outer package.
            return parent.parent.name == DEVIN_SKILL_DIR_NAME
    return False

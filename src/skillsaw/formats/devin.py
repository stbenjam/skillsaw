"""Devin CLI and Devin Desktop repository-context vocabulary.

Devin reads both its preferred ``.devin`` directory and the legacy
``.windsurf`` spelling.  Keep the shared names here so discovery, lint-tree
attachment, and structural validation cannot drift apart.

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


def is_native_skill_dir(path: Path) -> bool:
    """Whether *path* descends from a Devin or Windsurf skill collection."""
    return any(
        parent.name == "skills" and parent.parent.name in TOOL_DIR_NAMES for parent in path.parents
    )

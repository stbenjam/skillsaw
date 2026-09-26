"""Attach Pi resources through the shared tree builder's containment/dedup seam."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional, TYPE_CHECKING

from .lint_target import LintTarget
from .blocks import ContextFileBlock

if TYPE_CHECKING:
    from .lint_tree import _TreeBuildState
from .blocks.pi import (
    PiSettingsBlock,
    PiSkillBlock,
    PiSkillNode,
    PiPromptBlock,
    PiThemeBlock,
    PiExtensionNode,
)
from .discovery.pi import local_path, package_resources, project_resources
from .formats.pi import RESOURCE_FIELDS
from .blocks.pi_frontmatter import parse_pi_frontmatter
from .utils import read_text
from .paths import safe_is_file

_CLASSES = {
    "skills": PiSkillBlock,
    "prompts": PiPromptBlock,
    "themes": PiThemeBlock,
    "extensions": PiExtensionNode,
}


def _attach(
    state: _TreeBuildState,
    parent: LintTarget,
    paths: Iterable[Path],
    kind: str,
    owner: Optional[Path] = None,
) -> None:
    for path in paths:
        if kind == "prompts":
            # Configured prompts can also be another package's skill or prose.
            # Let those semantic owners attach before claiming the shared path.
            state.pi_prompts.append((parent, path, owner))
            continue
        if kind == "skills" and path.name == "SKILL.md":
            if state.context.resolve_path(path.parent) in state.portable_skill_dirs:
                # Other consumers retain their portable skill role in dual packages.
                continue
            _attach_skill_directory(state, parent, path, owner)
            continue
        if kind == "skills" and path.name != "SKILL.md":
            parsed = parse_pi_frontmatter(read_text(path) or "")
            description = parsed.data.get("description") if parsed.data is not None else None
            if parsed.error or not isinstance(description, str) or not description.strip():
                # Pi ignores ordinary Markdown documentation among flat skills.
                continue
        state.add_block(parent, path, _CLASSES[kind], owner=owner)


def _attach_skill_directory(
    state: _TreeBuildState, parent: LintTarget, skill_md: Path, owner: Optional[Path]
) -> None:
    """Attach a directory-style skill with its support files, as Pi loads it.

    The entry block stays ``PiSkillBlock`` so the native metadata contract
    applies; the ``references/`` prose attaches through the same seam the
    portable skill path uses. Flat ``*.md`` skills have no directory and
    stay single-file.
    """
    skill_path = skill_md.parent
    node = PiSkillNode(path=skill_path)
    node.plugin_owner = owner
    state.add_block(node, skill_md, PiSkillBlock, owner=owner)
    if not node.children:
        # Another role already owns this SKILL.md; an empty container
        # would report an unreachable skill.
        return
    # A project-level .pi/ skill has no owning package; its own directory
    # is then the boundary a references/ symlink may not leave.
    state.add_skill_references(node, skill_path, containment_root=owner or skill_path, owner=owner)
    parent.children.append(node)


def attach_pi_prompts(state: _TreeBuildState) -> None:
    """Attach configured prompt prose after its existing semantic owners."""
    for parent, path, owner in state.pi_prompts:
        state.add_block(parent, path, PiPromptBlock, owner=owner)


def attach_pi_resources(state: _TreeBuildState, parent: LintTarget, package: Path) -> None:
    context = state.context
    for kind in RESOURCE_FIELDS:
        _attach(
            state,
            parent,
            package_resources(package, kind, context.root_path, context.is_path_excluded),
            kind,
            owner=package,
        )


def attach_pi_projects(state: _TreeBuildState, root: LintTarget) -> None:
    context = state.context
    for directory in context.agent_tool_dirs(".pi"):
        block = state.add_parser_block(root, directory / "settings.json", PiSettingsBlock)
        data = block.raw_data if block is not None else None
        for name in ("SYSTEM.md", "APPEND_SYSTEM.md"):
            state.add_block(root, directory / name, ContextFileBlock)
        for kind in RESOURCE_FIELDS:
            paths = project_resources(directory, kind, context.root_path, context.is_path_excluded)
            _attach(state, root, sorted(set(paths)), kind)
        if isinstance(data, dict) and isinstance(data.get("packages"), list):
            for entry in data["packages"]:
                source = entry.get("source") if isinstance(entry, dict) else entry
                if isinstance(source, str):
                    path = local_path(directory, source, context.root_path, settings=True)
                    if path is not None and safe_is_file(path):
                        _attach(state, root, [path], "extensions")

"""
Build the repository lint tree — single discovery entrypoint.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Callable, List, Set, TYPE_CHECKING

from .lint_target import LintTarget, PluginNode, SkillNode

if TYPE_CHECKING:
    from .context import RepositoryContext


def build_lint_tree(context: "RepositoryContext") -> LintTarget:
    """Build a tree of all lintable objects in the repository."""
    from .rules.builtin.content_analysis import (
        CodeRabbitContentBlock,
        FileContentBlock,
        FrontmatterContentBlock,
    )

    root = LintTarget(path=context.root_path)
    seen: Set[Path] = set()
    exclude = getattr(context, "exclude_patterns", [])
    resolved_root = context.root_path.resolve()

    apm_compiled_roots: Set[Path] = set()
    if context.has_apm:
        from .context import RepositoryContext as _RC

        for compiled_dir_name in _RC.APM_COMPILED_DIRS:
            compiled_path = (context.root_path / compiled_dir_name).resolve()
            if compiled_path.is_dir():
                apm_compiled_roots.add(compiled_path)

    def _is_excluded(p: Path) -> bool:
        if not exclude:
            return False
        try:
            rel = str(p.resolve().relative_to(resolved_root))
        except ValueError:
            return False
        return any(fnmatch.fnmatch(rel, pat) for pat in exclude)

    def _is_in_compiled_dir(p: Path) -> bool:
        if not apm_compiled_roots:
            return False
        resolved = p.resolve()
        return any(resolved == excl or resolved.is_relative_to(excl) for excl in apm_compiled_roots)

    _INSTRUCTION_FILE_CATEGORIES = {
        "AGENTS.md": "agents-md",
        "CLAUDE.md": "claude-md",
        "GEMINI.md": "gemini-md",
    }

    def _add_content(
        parent: LintTarget,
        p: Path,
        category: str,
    ) -> None:
        resolved = p.resolve()
        if resolved in seen or not p.exists() or _is_excluded(p):
            return
        seen.add(resolved)
        if p.suffix == ".mdc":
            block = FrontmatterContentBlock(path=p, category=category)
        else:
            block = FileContentBlock(path=p, category=category)
        parent.children.append(block)

    # --- Root-level instruction files ---
    for f in context.instruction_files:
        cat = _INSTRUCTION_FILE_CATEGORIES.get(f.name, "instruction")
        _add_content(root, f, cat)

    _add_content(root, context.root_path / ".github" / "copilot-instructions.md", "instruction")
    _add_content(root, context.root_path / ".cursorrules", "instruction")

    cursor_rules_dir = context.root_path / ".cursor" / "rules"
    if cursor_rules_dir.is_dir() and not _is_in_compiled_dir(cursor_rules_dir):
        for mdc in sorted(cursor_rules_dir.glob("*.mdc")):
            _add_content(root, mdc, "instruction")

    kiro_steering = context.root_path / ".kiro" / "steering"
    if kiro_steering.is_dir():
        for md in sorted(kiro_steering.glob("*.md")):
            _add_content(root, md, "instruction")

    _add_content(root, context.root_path / ".windsurfrules", "instruction")

    clinerules = context.root_path / ".clinerules"
    if clinerules.is_file():
        _add_content(root, clinerules, "instruction")
    elif clinerules.is_dir():
        for md in sorted(clinerules.glob("*.md")):
            _add_content(root, md, "instruction")

    # --- Skills ---
    for skill_path in context.skills:
        skill_node = SkillNode(path=skill_path)
        _add_content(skill_node, skill_path / "SKILL.md", "skill")
        refs_dir = skill_path / "references"
        if refs_dir.is_dir():
            for ref_file in sorted(refs_dir.glob("*.md")):
                _add_content(skill_node, ref_file, "skill-ref")
        root.children.append(skill_node)

    # --- Plugins ---
    for plugin_path in context.plugins:
        if _is_in_compiled_dir(plugin_path):
            continue
        plugin_node = PluginNode(path=plugin_path)

        commands_dir = plugin_path / "commands"
        if commands_dir.is_dir():
            for cmd_file in sorted(commands_dir.glob("*.md")):
                _add_content(plugin_node, cmd_file, "command")

        agents_dir = plugin_path / "agents"
        if agents_dir.is_dir():
            for agent_file in sorted(agents_dir.glob("*.md")):
                _add_content(plugin_node, agent_file, "agent")

        rules_dir = plugin_path / "rules"
        if rules_dir.is_dir():
            for rule_file in sorted(rules_dir.rglob("*.md")):
                _add_content(plugin_node, rule_file, "rule")

        root.children.append(plugin_node)

    # --- .coderabbit.yaml ---
    cr_blocks = CodeRabbitContentBlock.gather(context, seen, _is_excluded)
    if cr_blocks:
        cr_container = LintTarget(path=context.root_path / ".coderabbit.yaml")
        cr_container.children.extend(cr_blocks)
        root.children.append(cr_container)

    # --- APM source directories ---
    if context.has_apm:
        apm_dir = context.root_path / ".apm"

        apm_instructions = apm_dir / "instructions"
        if apm_instructions.is_dir():
            for md in sorted(apm_instructions.glob("*.instructions.md")):
                _add_content(root, md, "instruction")

        apm_agents = apm_dir / "agents"
        if apm_agents.is_dir():
            for md in sorted(apm_agents.glob("*.agent.md")):
                _add_content(root, md, "agent")

        apm_prompts = apm_dir / "prompts"
        if apm_prompts.is_dir():
            for md in sorted(apm_prompts.glob("*.md")):
                _add_content(root, md, "prompt")

        apm_chatmodes = apm_dir / "chatmodes"
        if apm_chatmodes.is_dir():
            for md in sorted(apm_chatmodes.glob("*.md")):
                _add_content(root, md, "chatmode")

        apm_context = apm_dir / "context"
        if apm_context.is_dir():
            for md in sorted(apm_context.glob("*.md")):
                _add_content(root, md, "context")

    # --- Extra content paths from config ---
    for glob_pattern in getattr(context, "content_paths", []):
        for extra in sorted(context.root_path.glob(glob_pattern)):
            if extra.is_file():
                _add_content(root, extra, "extra")

    return root

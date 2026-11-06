"""Attach Codex instruction content and requested selection inputs."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Sequence

from .blocks.codex import CodexConfigBlock
from .blocks.base import ContentBlock
from .blocks.content import AgentsMdBlock, CodexInstructionBlock, ExtraBlock, ReadmeBlock
from .blocks.frontmatter import FrontmatteredBlock
from .codex_instructions import CodexInstructionFileNode, CodexInstructionsNode
from .discovery.codex_instructions import project_configs, project_directories, select_instructions
from .discovery.excludes import is_root_or_ancestor_excluded
from .formats.codex import CODEX_HOOKS_FILENAME
from .formats.codex_instructions import (
    DEFAULT_MAX_BYTES,
    TOML_INTEGER_MAX,
    candidate_filenames,
    contains_out_of_range_integer,
)
from .paths import relative_to_str

if TYPE_CHECKING:
    from .lint_tree import _TreeBuildState


def attach_codex_instructions(state: _TreeBuildState) -> None:
    context = state.context
    options = context.codex_instructions
    assert options is not None
    resolve = context.resolve_path
    node = CodexInstructionsNode(
        path=context.root_path, root_path=context.root_path, requested_cwd=options.cwd
    )
    try:
        directories = project_directories(context.root_path, options.cwd, resolve=resolve)
    except (ValueError, OSError) as error:
        node.issues.append(str(error))
        state.root.children.append(node)
        return
    node.cwd = directories[-1]
    if is_root_or_ancestor_excluded(node.cwd, context.root_path, context.is_path_excluded):
        node.issues.append("Codex cwd is excluded from the requested authoring scope")
    if not context.lint_external_content and context.is_externally_sourced(node.cwd):
        node.issues.append("Codex cwd is outside the retained authoring scope")
    configs = {resolve(block.path): block for block in state.root.find(CodexConfigBlock)}
    limit = DEFAULT_MAX_BYTES
    fallbacks = ()
    merged = {}
    origins = {}
    settings = ("project_doc_max_bytes", "project_doc_fallback_filenames")
    for candidate in project_configs(
        directories, resolve=resolve, is_excluded=context.is_path_excluded
    ):
        if candidate.path.name == CODEX_HOOKS_FILENAME:
            if candidate.issue is None and (
                context.lint_external_content or not context.is_externally_sourced(candidate.path)
            ):
                state.add_codex_hooks(state.root, candidate.path)
            continue
        if candidate.issue:
            node.issues.append(candidate.issue)
            continue
        path = candidate.path
        label = relative_to_str(path, context.root_path) or str(path)
        if not context.lint_external_content and context.is_externally_sourced(path):
            node.issues.append(f"{label}: configuration is outside the retained authoring scope")
            continue
        config = configs.get(resolve(path))
        if config is None:
            config = state.add_codex_config(state.root, path)
            if config is not None:
                configs[resolve(path)] = config
        if config is None:
            node.issues.append(f"{label}: configuration is not in the lint tree")
            continue
        node.config_sources.append(candidate)
        if config.parse_error:
            node.issues.append(f"{label}: {config.parse_error}")
            continue
        data = config.raw_data or {}
        invalid_keys = [key for key in settings if contains_out_of_range_integer(data.get(key))]
        if invalid_keys:
            # Python's TOML parser accepts integers Codex cannot parse. A
            # later override cannot repair an unparseable project layer.
            node.issues.append(
                f"{label}: integer outside Codex's signed 64-bit TOML integer range in "
                + ", ".join(invalid_keys)
            )
            continue
        for key in settings:
            if key in data:
                merged[key] = data[key]
                origins[key] = label
    if options.project_doc_max_bytes is not None:
        merged["project_doc_max_bytes"] = options.project_doc_max_bytes
        origins["project_doc_max_bytes"] = "explicit codex-instructions analysis input"
    if options.project_doc_fallback_filenames is not None:
        merged["project_doc_fallback_filenames"] = list(options.project_doc_fallback_filenames)
        origins["project_doc_fallback_filenames"] = "explicit codex-instructions analysis input"
    if "project_doc_max_bytes" in merged:
        value = merged["project_doc_max_bytes"]
        node.limit_source = origins["project_doc_max_bytes"]
        if type(value) is not int or not 0 <= value <= TOML_INTEGER_MAX:
            node.issues.append(
                f"{node.limit_source}: project_doc_max_bytes must be a non-negative integer "
                f"at most {TOML_INTEGER_MAX}"
            )
        else:
            limit = value
    if "project_doc_fallback_filenames" in merged:
        value = merged["project_doc_fallback_filenames"]
        node.fallback_source = origins["project_doc_fallback_filenames"]
        if not isinstance(value, list) or not all(isinstance(name, str) for name in value):
            node.issues.append(
                f"{node.fallback_source}: project_doc_fallback_filenames must be a list of strings"
            )
        else:
            fallbacks = tuple(value)
    node.max_bytes = limit
    node.filenames, node.ignored_fallbacks = candidate_filenames(fallbacks)
    node.sources = select_instructions(
        directories, node.filenames, resolve=resolve, is_excluded=context.is_path_excluded
    )
    attach_instruction_content(state, [source.path for source in node.sources if not source.issue])
    state.root.children.append(node)
    state.root.invalidate_find_cache()


def attach_instruction_content(
    state: _TreeBuildState,
    paths: Sequence[Path],
    *,
    suppressed: frozenset[Path] = frozenset(),
) -> None:
    """Keep semantic owners; give untyped prose the instruction role."""
    if not paths:
        return
    resolve = state.context.resolve_path
    claimed = {}
    readmes = {}
    extras = {}
    for parent in state.root.walk():
        for block in parent.children:
            resolved = resolve(block.path)
            if isinstance(block, ReadmeBlock):
                readmes[resolved] = (parent, block)
            elif type(block) is ExtraBlock:
                extras[resolved] = (parent, block)
            elif not isinstance(claimed.get(resolved), (ContentBlock, FrontmatteredBlock)):
                # A physical file may have both config and prose roles.
                # Validate retained prose regardless of attachment order.
                claimed[resolved] = block
    for path in paths:
        resolved = resolve(path)
        if resolved is None:
            continue
        owner = claimed.get(resolved)
        if isinstance(owner, (ContentBlock, FrontmatteredBlock)):
            # Record file validation separately from the existing prose
            # parser, including empty frontmattered files without a body.
            state.add_parser_block(
                owner, owner.path, CodexInstructionFileNode, owner=owner.plugin_owner
            )
            continue
        existing = extras.get(resolved) or readmes.get(resolved)
        if resolved in claimed and (owner is None or existing is None):
            continue
        # Generic prose still gains its instruction role beside any config
        # role. A README also retains its separate display role.
        block_type = AgentsMdBlock if path.name == "AGENTS.md" else CodexInstructionBlock
        if existing is not None:
            parent, previous = existing
            block = state.add_parser_block(
                parent,
                path,
                block_type,
                owner=previous.plugin_owner,
                content_suppressed=previous.content_suppressed or path in suppressed,
            )
            if block is not None:
                block.externally_sourced = previous.externally_sourced
                if type(previous) is ExtraBlock:
                    block.children = previous.children
                    parent.children.remove(previous)
                    state.seen_roles.discard((resolved, ExtraBlock))
        else:
            state.add_block(state.root, path, block_type, content_suppressed=path in suppressed)
        claimed[resolved] = None
    state.root.invalidate_find_cache()

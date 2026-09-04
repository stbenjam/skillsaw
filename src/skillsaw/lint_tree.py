"""
Build the repository lint tree — single discovery entrypoint.
"""

from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, TYPE_CHECKING, Tuple

from .diagnostics import safe_display

from .blocks import (
    AgentBlock,
    AgentMemoryBlock,
    AgentMemoryIndexBlock,
    AgentPluginMcpBlock,
    AgentsMdBlock,
    ChatmodeBlock,
    ClaudeMdBlock,
    ClineWorkflowBlock,
    CodeRabbitContentBlock,
    ClaudeHooksBlock,
    CodexConfigBlock,
    CodexConfigHooksBlock,
    CodexHooksBlock,
    CodexInlineHooksBlock,
    CodexInlineMcpBlock,
    CommandBlock,
    ContextFileBlock,
    CopilotAgentBlock,
    CopilotPromptBlock,
    CursorCommandBlock,
    CursorHooksBlock,
    CursorMcpBlock,
    CursorPromptHookBlock,
    CursorRuleBlock,
    DevinGlobalRuleBlock,
    DevinRuleBlock,
    DevinSkillBlock,
    ExtraBlock,
    GeminiMdBlock,
    GrokAgentBlock,
    GrokCommandBlock,
    GrokConfigBlock,
    GrokHooksBlock,
    GrokInlineHooksBlock,
    GrokInlineMcpBlock,
    GrokMcpBlock,
    GrokPluginHooksBlock,
    GrokRuleBlock,
    HooksBlock,
    InstructionBlock,
    McpBlock,
    McpRegistryNpmPackageBlock,
    McpRegistryServerBlock,
    MuseHooksBlock,
    OpenAIMetadataBlock,
    OpenCodeAgentBlock,
    OpenCodeCommandBlock,
    OpenCodeConfigBlock,
    OpenCodeMcpBlock,
    PluginRuleBlock,
    PromptBlock,
    PromptfooPromptBlock,
    QwenMdBlock,
    ReadmeBlock,
    SettingsBlock,
    SkillBlock,
    SkillRefBlock,
    SkillsLockBlock,
    VsCodeMcpBlock,
)
from .formats.codex import (
    CODEX_CONFIG_FILENAME,
    CODEX_DIR_NAME,
    CODEX_HOOKS_FILENAME,
    codex_config_hooks,
    codex_declared_hook_files,
    codex_declared_mcp_files,
    codex_inline_hooks,
    codex_inline_mcp_servers,
)
from .discovery import AGENT_MEMORY_DIR, AGENT_MEMORY_INDEX
from .discovery.opencode import contained_instruction_globs
from .formats import devin, grok, muse
from .utils import has_apm_generated_header, read_text
from .paths import (
    contained_resolve,
    has_parent_traversal,
    is_absolute_path,
    path_within_roots,
    safe_exists,
    safe_is_dir,
    safe_is_file,
    safe_resolve,
)
from .formats.promptfoo import (
    extract_file_refs,
    is_promptfoo_config,
    resolve_file_ref,
)
from .lint_target import (
    AgentPluginConfigNode,
    AgentPluginNode,
    LintTarget,
    ApmConfigNode,
    ApmNode,
    CodexMarketplaceConfigNode,
    CodexPluginConfigNode,
    CodexPluginNode,
    DevinSkillNode,
    GrokMarketplaceConfigNode,
    GrokMarketplaceIndexNode,
    GrokPluginConfigNode,
    GrokPluginNode,
    MarketplaceConfigNode,
    MarketplaceNode,
    PluginNode,
    PromptfooConfigNode,
    SkillNode,
    CodeRabbitNode,
)

logger = logging.getLogger(__name__)

# Subdirectories Cline's rules loader skips when concatenating .clinerules/
# into the system prompt. Mirrors the exclusion list in cline/cline's
# cline-rules.ts: workflows/ and skills/ load on demand, hooks/ are
# executables.
_CLINE_EXCLUDED_DIRS = frozenset({"workflows", "hooks", "skills"})

# Editor-directory content globs, as (editor dir, subdirectory, pattern,
# block-class name). The ``*.instructions.md`` sweep consults this to decide
# where to stand aside, so "which loop owns this file" has one answer rather
# than two that can disagree — and disagreeing drops the file from the tree.
_EDITOR_GLOBS = (
    (".cursor", "rules", "**/*.mdc", "CursorRuleBlock"),
    (".cursor", "commands", "**/*.md", "CursorCommandBlock"),
    (".github", "agents", "**/*.md", "CopilotAgentBlock"),
    (".github", "prompts", "**/*.prompt.md", "CopilotPromptBlock"),
    (".github", "chatmodes", "**/*.chatmode.md", "CopilotAgentBlock"),
    (".clinerules", "workflows", "**/*.md", "ClineWorkflowBlock"),
    (".devin", "rules", "**/*.md", "DevinRuleBlock"),
    (".windsurf", "rules", "**/*.md", "DevinRuleBlock"),
    # OpenCode 2.0 renamed each content directory to its plural and still
    # loads the 1.x singular, so both are listed. ``mode``/``modes`` are
    # deliberately absent — see ``_OPENCODE_FLAT_DIRS``.
    (".opencode", "commands", "**/*.md", "OpenCodeCommandBlock"),
    (".opencode", "command", "**/*.md", "OpenCodeCommandBlock"),
    (".opencode", "agents", "**/*.md", "OpenCodeAgentBlock"),
    (".opencode", "agent", "**/*.md", "OpenCodeAgentBlock"),
)

# The OpenCode directories the loader reads *flat*: ``{mode,modes}/*.md``,
# the pre-``agent`` spelling of a primary agent. They are kept out of
# ``_EDITOR_GLOBS`` on purpose. That table tells the repository-wide
# ``*.instructions.md`` sweep where to stand aside, and its match is
# lexical — it does not check depth — so listing a flat directory there
# would make the sweep yield a *nested* ``modes/x/y.instructions.md`` to a
# loop that only ever claims the top level, dropping the file from the tree
# entirely. Standing aside is only safe where the owning glob is recursive.
# Nothing is lost: OpenCode does not load a nested file there either, so the
# sweep claiming it as ordinary instruction prose is the right answer.
_OPENCODE_FLAT_DIRS = (
    ("modes", "OpenCodeAgentBlock"),
    ("mode", "OpenCodeAgentBlock"),
)

# Every OpenCode markdown directory the tree attaches, as (subdirectory,
# glob, block-class name) — the recursive ones derived from _EDITOR_GLOBS so
# the two tables cannot drift, plus the flat ones above.
_OPENCODE_CONTENT_DIRS = tuple(
    (sub, pattern, cls) for editor, sub, pattern, cls in _EDITOR_GLOBS if editor == ".opencode"
) + tuple((sub, "*.md", cls) for sub, cls in _OPENCODE_FLAT_DIRS)

#: OpenCode reads its project config under either extension, in either
#: location. Both are attached when both exist, so each is validated on its
#: own terms — no rule reports the pairing itself, since which one OpenCode
#: loads is its business rather than a defect in either file.
_OPENCODE_CONFIG_NAMES = ("opencode.json", "opencode.jsonc")

# Authored APM content directories, in lint-tree attachment order. Keeping the
# directory, file convention, and semantic block together makes format support
# a data change rather than another nested branch in the tree orchestrator.
_APM_CONTENT_GLOBS = (
    ("instructions", "*.instructions.md", InstructionBlock),
    ("agents", "*.agent.md", AgentBlock),
    ("prompts", "*.md", PromptBlock),
    ("chatmodes", "*.md", ChatmodeBlock),
    ("context", "*.md", ContextFileBlock),
)


if TYPE_CHECKING:
    from .context import RepositoryContext


@dataclass
class _TreeBuildState:
    """Shared state and attachment primitives for one lint-tree build."""

    context: "RepositoryContext"
    root: LintTarget
    repo_root: Path
    seen: Set[Path] = field(default_factory=set)
    seen_roles: Set[Tuple[Path, type]] = field(default_factory=set)
    # Two indexes over ``seen_roles``, written beside it: "is this file
    # already in the tree as hooks / as MCP" is asked once per plugin, and
    # scanning every role on each question is O(plugins x blocks) on a
    # marketplace with hundreds of each.
    hooks_paths: Set[Path] = field(default_factory=set)
    mcp_paths: Set[Path] = field(default_factory=set)
    openai_seen: Set[Tuple[Path, Path]] = field(default_factory=set)
    opencode_configs: List[OpenCodeConfigBlock] = field(default_factory=list)

    def resolve_repo_path(self, path: Path) -> Path | None:
        """Resolve *path* only when repository containment is safe."""
        return contained_resolve(path, self.repo_root)

    def add_block(
        self,
        parent: LintTarget,
        p: Path,
        block_cls: type,
        owner: Path | None = None,
        content_suppressed: bool = False,
    ) -> None:
        """Add one safely resolved block unless its role is already present."""
        resolved = self.resolve_repo_path(p)
        if (
            resolved is None
            or resolved in self.seen
            or not safe_exists(resolved)
            or self.context.is_path_excluded(p)
        ):
            return
        self.seen.add(resolved)
        self._record_role(resolved, block_cls)
        block = block_cls(path=p)
        block.plugin_owner = owner
        block.content_suppressed = content_suppressed
        parent.children.append(block)

    def add_parser_block(
        self,
        parent: LintTarget,
        p: Path,
        block_cls: type,
        owner: Path | None = None,
        content_suppressed: bool = False,
    ) -> Optional[LintTarget]:
        """Attach a structured document once for each parser role.

        A JSON document may legitimately contain both hooks and MCP servers.
        Path-only deduplication would hide whichever parser runs second, while
        role-aware deduplication still prevents duplicate findings when two
        discovery paths select the same parser.
        """
        if self._claim_parser_role(p, block_cls) is None:
            return None
        block = block_cls(path=p)
        block.plugin_owner = owner
        block.content_suppressed = content_suppressed
        parent.children.append(block)
        return block

    def attach_prebuilt(self, parent: LintTarget, block: LintTarget) -> Optional[LintTarget]:
        """Attach an already-constructed block under the same contract.

        The seam for a block the caller has to build itself — one carrying a
        payload rendered from the file rather than read off it — so
        containment, exclusion and role deduplication are still decided in
        the one place :meth:`add_parser_block` decides them.
        """
        if self._claim_parser_role(block.path, type(block)) is None:
            return None
        parent.children.append(block)
        return block

    def _claim_parser_role(self, p: Path, block_cls: type) -> Optional[Path]:
        """Claim one parser role over *p*, or ``None`` if it is not ours.

        Containment, existence, exclusion and role deduplication, in that
        order — the contract both attachment paths share.
        """
        resolved = self.resolve_repo_path(p)
        if resolved is None:
            return None
        role = (resolved, block_cls)
        if (
            role in self.seen_roles
            or not safe_is_file(resolved)
            or self.context.is_path_excluded(p)
        ):
            return None
        # seen_roles only — never the path-only ``seen`` set: a manifest can
        # declare ``hooks``/``mcpServers`` at any in-plugin markdown file,
        # and poisoning ``seen`` would drop that file from every content
        # rule that attaches later.
        self._record_role(resolved, block_cls)
        return resolved

    def _record_role(self, resolved: Path, block_cls: type) -> None:
        """Record one attached role, and index it by the two roles asked about."""
        self.seen_roles.add((resolved, block_cls))
        if issubclass(block_cls, HooksBlock):
            self.hooks_paths.add(resolved)
        elif issubclass(block_cls, McpBlock):
            self.mcp_paths.add(resolved)

    def add_openai_metadata(
        self,
        parent: LintTarget,
        path: Path,
        *,
        metadata_root: Path,
        containment_root: Path,
    ) -> None:
        """Attach structured OpenAI metadata."""
        # Existence first: this runs once per SkillNode, and `agents/
        # openai.yaml` is absent in the overwhelming majority of them — the
        # three resolves below cost a realpath each and answer nothing when
        # there is no file to attach.
        if not safe_is_file(path) or self.context.is_path_excluded(path):
            return
        resolved = safe_resolve(path)
        root = safe_resolve(containment_root)
        owner = safe_resolve(metadata_root)
        if (
            resolved is None
            or root is None
            or owner is None
            or (resolved, owner) in self.openai_seen
            or not resolved.is_relative_to(root)
        ):
            return
        # Metadata paths have owner-relative semantics, so the same contained
        # file may need validation once for each skill that links to it. Keep
        # this separate from the content-block dedupe set for the same reason.
        self.openai_seen.add((resolved, owner))
        block = OpenAIMetadataBlock(
            path=path,
            metadata_root=metadata_root,
            containment_root=containment_root,
        )
        parent.children.append(block)


def _attached_as_hooks(state: _TreeBuildState, path: Path) -> bool:
    """Whether *path* is already in the tree under some hooks class.

    Every hooks class is read by the same security rules, so which one a
    file arrived under does not matter here — a second block for it would
    report each of its commands twice. The generic root attach and the
    Claude branch both run before a Codex manifest's declared files, and a
    manifest may name any of the files they placed: the project layer's
    ``.codex/hooks.json``, the conventional ``hooks/hooks.json``, or
    another tool's ``.muse/hooks.json`` or ``.cursor/hooks.json``.
    """
    resolved = state.resolve_repo_path(path)
    return resolved is not None and resolved in state.hooks_paths


def _attached_as_mcp(state: _TreeBuildState, path: Path) -> bool:
    """Whether *path* is already in the tree under some MCP class.

    The counterpart of :func:`_attached_as_hooks`, and needed for the same
    reason: every MCP class is read by the same security and policy rules,
    so a second block for one file reports each of its servers twice. The
    generic root attach runs before the plugin pass and places the
    repository root's ``.mcp.json``, which for a repo-root plugin is that
    plugin's own conventional file under a different class.
    """
    resolved = state.resolve_repo_path(path)
    return resolved is not None and resolved in state.mcp_paths


def _add_project_hooks(
    state: _TreeBuildState,
    root: LintTarget,
    path: Path,
    block_cls: type,
) -> None:
    """Attach a project-layer hooks file unless another host already has it.

    ``.cursor/hooks.json``, ``.codex/hooks.json`` and ``.muse/hooks.json``
    are three names for one shape, and a repository supporting several tools
    commonly symlinks them to a single file. Each host's loop runs
    independently, so without this the one resolved file gets a block per
    host and the security rules report each of its commands once per block.
    Whichever host reaches it first keeps it: the security rules read every
    hooks class alike, and the later host's shape rule simply does not see a
    file that host chose to share. Grok contributes a directory of candidates
    (``.grok/hooks/*.json``) rather than one well-known name, and its loop
    runs last, so a Grok file symlinked to another host's is that host's
    block.
    """
    if _attached_as_hooks(state, path):
        return
    state.add_parser_block(root, path, block_cls)


def _add_codex_config(state: _TreeBuildState, root: LintTarget, path: Path) -> None:
    """Attach a ``.codex/config.toml``, and its ``[hooks]`` tables under it.

    Two committed executable surfaces in one file. Codex reads lifecycle
    hooks from ``[hooks]`` as well as from ``hooks.json`` and merges the two,
    and ``[mcp_servers.<name>]`` is where a Codex project declares its MCP
    servers — there is no ``.codex/mcp.json``. The document itself is one
    node either way, so a config declaring neither is still in the tree.

    Every one in the repository, not only the root's. Measured against
    codex-cli 0.153.0: Codex merges a layer from every directory on the
    chain from the git repo root down to the cwd, so a committed
    ``services/billing/.codex/config.toml`` is live for anyone working in
    that subtree — and dormant, not absent, for everyone else. Nothing above
    the repository root is ever read, which is also the only place this walk
    cannot reach.

    The hooks child is attached whenever there are hooks to check, and also
    when the file did not parse, so ``codex-hooks-valid`` has something to
    report the failure on — a config Codex cannot read stops it starting in
    the project at all.
    """
    config = state.add_parser_block(root, path, CodexConfigBlock)
    if config is None:
        return
    # One hooks block per resolved file, for the reason
    # ``_add_project_hooks`` documents: a package's config symlinked to the
    # root's is one file, and two blocks would report each of its commands
    # twice. ``hooks.json`` and ``config.toml`` are two paths, so a directory
    # carrying both keeps a block for each — Codex merges them.
    if _attached_as_hooks(state, path):
        return
    data, error = config.raw_data, config.parse_error
    document = codex_config_hooks(data) if data is not None else None
    if error is None and document is None:
        return
    state.attach_prebuilt(
        config, CodexConfigHooksBlock(path=path, inline_data=document, toml_error=error)
    )


def _claim_attached_hooks(
    state: _TreeBuildState,
    root: LintTarget,
    path: Path,
    owner: Path,
) -> bool:
    """Claim an already-attached hooks file for *owner*, if there is one.

    Answers "is this file already in the tree?" for the declared-files loop
    and, when it is, records the plugin that declared it. Nothing but the
    manifest names such a file, so the declaration is the only evidence of
    ownership there is — and without it ``skillsaw docs`` lists the plugin
    without its hooks. An attach that already recorded an owner (the Claude
    branch, the Codex cluster's conventional file) keeps it.

    Only the tree root is scanned, which is where every ownerless attach
    puts a hooks block: the project layer's ``.codex/hooks.json`` and
    another tool's ``.muse/hooks.json`` or ``.cursor/hooks.json``. Scanning
    the subtree would mean ``find()`` mid-build, whose per-node memo the
    attaches still to come would invalidate.
    """
    if not _attached_as_hooks(state, path):
        return False
    resolved = state.resolve_repo_path(path)
    for child in root.children:
        if (
            isinstance(child, HooksBlock)
            and child.plugin_owner is None
            and safe_resolve(child.path) == resolved
        ):
            child.plugin_owner = owner
    return True


def _attach_apm_skills(
    state: _TreeBuildState,
    apm_node: ApmNode,
    apm_skills: Path,
) -> None:
    """Attach authored APM skills and their Markdown references."""
    if not apm_skills.is_dir():
        return

    for skill_path in state.context.skills:
        if not (safe_resolve(skill_path) or skill_path).is_relative_to(
            safe_resolve(apm_skills) or apm_skills
        ):
            continue
        skill_node = SkillNode(path=skill_path)
        state.add_block(skill_node, skill_path / "SKILL.md", SkillBlock)
        refs_dir = skill_path / "references"
        if refs_dir.is_dir():
            for ref_file in sorted(refs_dir.glob("*.md")):
                state.add_block(skill_node, ref_file, SkillRefBlock)
        apm_node.children.append(skill_node)


def _attach_apm_tree(
    state: _TreeBuildState,
) -> None:
    """Attach APM's manifest and authored primitives at their original stage."""
    context = state.context
    if not context.has_apm:
        return

    apm_yml = context.root_path / "apm.yml"
    if apm_yml.exists() and not context.is_path_excluded(apm_yml):
        state.root.children.append(ApmConfigNode(path=apm_yml))

    # `.apm/` holds a package's authored primitives. A consumer-only
    # manifest — `apm.yml` with `dependencies:`/`targets:` and no authored
    # content — has no `.apm/` directory, so don't invent an ApmNode for a
    # path that doesn't exist (issue #472).
    apm_dir = context.root_path / ".apm"
    if not apm_dir.is_dir():
        return

    apm_node = ApmNode(path=apm_dir)
    for dirname, pattern, block_cls in _APM_CONTENT_GLOBS:
        content_dir = apm_dir / dirname
        if not content_dir.is_dir():
            continue
        for markdown_file in sorted(content_dir.glob(pattern)):
            state.add_block(apm_node, markdown_file, block_cls)

    # Hooks and settings inside .apm/ are supply-chain attack surfaces.
    state.add_block(apm_node, apm_dir / "hooks" / "hooks.json", ClaudeHooksBlock)
    state.add_block(apm_node, apm_dir / "settings.json", SettingsBlock)
    state.add_block(apm_node, apm_dir / "settings.local.json", SettingsBlock)

    _attach_apm_skills(state, apm_node, apm_dir / "skills")
    state.root.children.append(apm_node)


def build_lint_tree(context: "RepositoryContext") -> LintTarget:
    """Build a tree of all lintable objects in the repository."""
    # Imported here rather than at module scope: ``context`` reaches this
    # module through ``RepositoryContext.lint_tree``, so a top-level import
    # would close the cycle.
    from .context import RepositoryType

    _INSTRUCTION_FILE_BLOCK_TYPES = {
        "AGENTS.md": AgentsMdBlock,
        "CLAUDE.md": ClaudeMdBlock,
        "GEMINI.md": GeminiMdBlock,
        "QWEN.md": QwenMdBlock,
    }

    def _instruction_block_type(path: Path) -> type:
        """Return the semantic block for one discovered instruction file."""
        if path.name.lower() == "agents.md":
            return AgentsMdBlock
        return _INSTRUCTION_FILE_BLOCK_TYPES.get(path.name, InstructionBlock)

    root = LintTarget(path=context.root_path)
    repo_root = safe_resolve(context.root_path)
    if repo_root is None:
        message = f"Repository root could not be resolved: {context.root_path}"
        if message not in context.lint_tree_errors:
            context.lint_tree_errors.append(message)
        logger.error(message)
        root.set_parents()
        return root
    state = _TreeBuildState(context=context, root=root, repo_root=repo_root)

    _is_excluded = context.is_path_excluded
    _is_in_compiled_dir = context.in_apm_compiled_dir

    apm_source_root = (
        (safe_resolve((context.root_path / ".apm")) or (context.root_path / ".apm"))
        if context.has_apm
        else None
    )

    def _is_in_apm_source(p: Path) -> bool:
        """Return whether *p* belongs to the active APM source tree."""
        if apm_source_root is None:
            return False
        resolved = safe_resolve(p) or p
        return resolved == apm_source_root or resolved.is_relative_to(apm_source_root)

    # Editor directories the loops below will actually walk. Discovery drops
    # vendored and excluded ones, so this is narrower than "any directory
    # with the right name" — and the sweep must use the same set, or it
    # yields to an owner that never arrives.
    eligible_tool_dirs = {
        editor: {
            resolved
            for directory in context.agent_tool_dirs(editor)
            if (resolved := safe_resolve(directory)) is not None
        }
        for editor in {editor for editor, _sub, _pattern, _cls in _EDITOR_GLOBS}
    }

    def _claimed_by_an_editor_dir(p: Path) -> bool:
        """Whether an editor-directory glob below will claim *p* itself.

        The repository-wide ``*.instructions.md`` sweep runs first and
        reserves paths in the global ``seen`` set, so a custom agent named
        ``reviewer.instructions.md`` would attach as an InstructionBlock —
        frontmatter linted as prose, and the instruction budget instead of
        the agent one. The sweep stands aside here so the specific owner
        wins, at whatever depth the file sits.

        Standing aside is conditional on that owner actually turning up, in
        two ways, because yielding to an owner that never runs drops the
        file from the tree entirely rather than merely misfiling it:

        * the pattern must match — ``.github/prompts`` takes
          ``*.prompt.md``, so an ``*.instructions.md`` there belongs to the
          sweep after all; and
        * the editor directory must be one the loops below will walk.
          Discovery keeps ``vendor/pkg/.github`` out of ``agent_tool_dirs``
          while the sweep still collects instruction files from it, so
          matching on the directory *name* alone would silently discard
          vendored content the linter reports.

        All of it reads from ``_EDITOR_GLOBS`` and ``agent_tool_dirs``, so
        the two halves cannot drift apart.
        """

        def _lexically_claimed(candidate: Path) -> bool:
            parts = candidate.parts
            # Stop before the filename: the pair must be ancestor directories.
            for index in range(len(parts) - 2):
                for editor, sub, pattern, _cls in _EDITOR_GLOBS:
                    if parts[index] != editor or parts[index + 1] != sub:
                        continue
                    if not fnmatch.fnmatch(candidate.name, pattern.rsplit("/", 1)[-1]):
                        continue
                    editor_dir = safe_resolve(Path(*parts[: index + 1]))
                    if editor_dir is not None and editor_dir in eligible_tool_dirs[editor]:
                        return True
            return False

        # A generic-looking symlink can point at a specifically parsed editor
        # file. Let the canonical target's owner win too, or the early
        # instruction sweep claims the resolved path and suppresses structural
        # validation when the editor loop arrives later.
        resolved = safe_resolve(p)
        return _lexically_claimed(p) or (resolved is not None and _lexically_claimed(resolved))

    # APM's Copilot target compiles `.apm/<kind>/` into the root
    # `.github/<kind>/`. Attaching both would report every finding twice and
    # point half of them at a generated file the author must not edit. The
    # matching `.apm/` source is the evidence — a `.github/prompts/` in a
    # repository with no `.apm/prompts/` is authored content and stays.
    apm_compiled_github: Set[Path] = set()
    if context.has_apm and context.apm_targets("copilot"):
        root_github = safe_resolve(context.root_path / ".github")
        for kind in ("agents", "prompts", "chatmodes", "instructions"):
            if root_github is not None and (context.root_path / ".apm" / kind).is_dir():
                apm_compiled_github.add(root_github / kind)
        # `.apm/instructions/` compiles to two places, not one: the
        # per-glob copies under `.github/instructions/` *and* the whole
        # concatenation as the root `copilot-instructions.md`. Guarding
        # only the directory would leave the root file attached beside its
        # own sources — the duplication this set exists to prevent.
        #
        # A file, unlike a directory, can say for itself whether it is
        # output, so require the stamp too. A source directory proves APM
        # *would* write here; the stamp proves it did. Demanding both keeps
        # a hand-written Copilot file linted — including one a user wrote
        # before adopting APM, and one written by an APM version that
        # compiles only the directory.
        root_copilot = context.root_path / ".github" / "copilot-instructions.md"
        if (
            root_github is not None
            and (context.root_path / ".apm" / "instructions").is_dir()
            and has_apm_generated_header(read_text(root_copilot))
        ):
            apm_compiled_github.add(root_github / "copilot-instructions.md")

    def _is_apm_compiled_github(path: Path) -> bool:
        """Whether *path* is APM output rather than authored content."""
        resolved = safe_resolve(path)
        return resolved is not None and resolved in apm_compiled_github

    # Nearest package ownership, with the roots resolved once per context.
    _contained_plugin_owner = context.contained_plugin_owning
    agent_plugin_roots = set(context.agent_plugin_roots())

    def _shadowed_by_agent_plugin_mcp(path: Path, agent_plugin_mcp: Path | None) -> bool:
        """Whether *path* is the portable ``mcp.json`` under another name.

        A dual-format package may symlink ``.mcp.json`` (or declare a Codex
        MCP file) at the portable ``mcp.json``. That document is already
        attached once as the Agent Plugins parser role, so a second parser
        role here would duplicate every policy and security finding.
        """
        return agent_plugin_mcp is not None and safe_resolve(path) == agent_plugin_mcp

    def _add_contained_plugin_block(
        parent: CodexPluginConfigNode | GrokPluginConfigNode | AgentPluginConfigNode,
        p: Path,
        block_cls: type,
        owner: Path | None = None,
    ) -> None:
        """Role-aware block attachment for a path that must stay inside its plugin.

        Conventional package files can be found without a manifest path
        declaration, so nothing else has checked where they resolve to. A
        symlink would otherwise read an external file under an in-repo path.
        """
        root = safe_resolve(parent.plugin_dir)
        resolved = safe_resolve(p)
        if root is None or resolved is None or not resolved.is_relative_to(root):
            return
        state.add_parser_block(parent, p, block_cls, owner=owner)

    def _inside_plugin(candidate: Path, plugin_resolved: Path) -> bool:
        """Inside *plugin_resolved*, and not inside a nested claimed plugin.

        Any claimed plugin directory strictly between the file and this
        plugin's root means the file is the nested plugin's to attach —
        otherwise a repo-root plugin's recursive ``rules/`` scan, or a
        manifest pointing ``commands`` at a directory holding another
        plugin, would tag nested files with the outer owner.
        ``seen_plugin_dirs`` is fully populated before the plugin loop makes
        the first call here.
        """
        resolved = safe_resolve(candidate)
        if resolved is None:
            return False
        for ancestor in resolved.parents:
            if ancestor == plugin_resolved:
                return True
            if ancestor in seen_plugin_dirs:
                return False
        return False

    def _add_plugin_prose(parent: LintTarget, plugin_dir: Path, owner: Path) -> None:
        """The one prose attach for every plugin container.

        ``commands/``, ``agents/``, ``rules/`` and README follow the same
        conventions across plugin ecosystems, so every claimed directory gets
        them here — the content and security rules must read this prose
        whoever owns it. Containment as in ``_add_contained_plugin_block``: a symlink
        would pull an external file under an in-repo name.
        """
        plugin_resolved = safe_resolve(plugin_dir)
        if plugin_resolved is None:
            return

        def _contained(p: Path) -> bool:
            return _inside_plugin(p, plugin_resolved)

        for dirname, block_cls, pattern in (
            ("commands", CommandBlock, "*.md"),
            ("agents", AgentBlock, "*.md"),
            ("rules", PluginRuleBlock, "**/*.md"),
        ):
            content_dir = plugin_dir / dirname
            if not safe_is_dir(content_dir):
                continue
            try:
                files = sorted(content_dir.glob(pattern))
            except OSError:
                continue
            for md in files:
                if _contained(md):
                    state.add_block(parent, md, block_cls, owner=owner)
        readme = plugin_dir / "README.md"
        if _contained(readme):
            state.add_block(parent, readme, ReadmeBlock, owner=owner)

    # --- Root-level instruction files (skip .apm/ — handled in APM section) ---
    # Only Devin Desktop reads ``agents.md`` case-insensitively, so that
    # spelling is an instruction file only where the repository carries other
    # Devin evidence; elsewhere ``docs/agents.md`` is a documentation page.
    devin_desktop = RepositoryType.DEVIN in context.repo_types
    for f in context.instruction_files:
        if _is_in_apm_source(f) or _claimed_by_an_editor_dir(f):
            continue
        if not devin_desktop and devin.is_desktop_agents_spelling(f.name):
            continue
        # APM writes .apm/instructions/ out to .github/instructions/. The
        # authored source attaches below; the copy attaches content-suppressed
        # so its content findings don't double the source's, while the
        # security rules still scan the copy that ships.
        compiled = _is_apm_compiled_github(f.parent)
        block_cls = _instruction_block_type(f)
        state.add_block(root, f, block_cls, content_suppressed=compiled)

    # --- .claude/settings.json (supply-chain attack surface) ---
    state.add_block(root, context.root_path / ".claude" / "settings.json", SettingsBlock)
    state.add_block(root, context.root_path / ".claude" / "settings.local.json", SettingsBlock)

    # --- Root-level .mcp.json (MCP server configuration) ---
    # A dual-format package may symlink both conventional paths to one file.
    # Prefer the portable parser role so ecosystem-neutral policy rules see
    # the executable surface once rather than reporting duplicate findings.
    root_agent_plugin_mcp = (
        safe_resolve(context.root_path / "mcp.json") if repo_root in agent_plugin_roots else None
    )
    root_native_mcp = context.root_path / ".mcp.json"
    if not _shadowed_by_agent_plugin_mcp(root_native_mcp, root_agent_plugin_mcp):
        state.add_block(root, root_native_mcp, McpBlock)

    # --- MCP Registry publisher metadata ---
    # server.json is not an MCP client configuration file: it describes one
    # published server, so it gets its own structured parser role and never
    # reaches content-quality rules as prose.
    registry_servers = context.mcp_registry_server_paths()
    for server_json in registry_servers:
        state.add_parser_block(root, server_json, McpRegistryServerBlock)
    if registry_servers:
        for package_json in context.package_json_paths():
            state.add_parser_block(root, package_json, McpRegistryNpmPackageBlock)

    # --- Editor-owned content directories (Cursor, Copilot/VS Code, Cline) ---
    # These tools read AGENTS.md for portable instructions — already attached
    # above — so nothing here re-implements an instruction format. What is
    # attached is the prose each tool keeps in its own directory and that
    # therefore ships in the repository: rules, slash commands, prompt files
    # and custom agents. Every one of them lands in an agent's context
    # window, so every one gets the content rules.
    #
    # All three resolve their configuration from the nearest enclosing
    # directory as well as the repository root, so a monorepo package can
    # carry its own — hence the walk-backed ``agent_tool_dirs`` rather than a
    # root-anchored lookup.
    def _readable_matches(directory: Path, pattern: str) -> List[Path]:
        """Every *pattern* match under *directory*, or nothing if it is unread.

        The four guards in this helper are what any glob of a repository directory
        needs, and a caller that skips the last one fails *silently*: a
        directory that cannot be read looks exactly like a directory with
        nothing in it, so the run stays green over content nobody scanned.
        Hence one helper rather than a guard per call site.
        """
        if not safe_is_dir(directory):
            return []
        # An excluded directory is not walked. Testing only each match would
        # let `exclude: [".cursor/rules"]` through — the pattern names the
        # directory and the matches are its children — leaving the files in
        # every content and security rule while format detection, which does
        # honour the directory, disagrees.
        if _is_excluded(directory):
            return []
        # Contain the glob *base*, not just each match: pathlib follows a
        # symlink at the base even though it will not follow one during
        # ``**`` descent, so a ``.clinerules -> /`` symlink would walk the
        # filesystem before a single match was rejected.
        if state.resolve_repo_path(directory) is None:
            return []
        try:
            return sorted(directory.glob(pattern))
        except OSError as exc:
            # A directory that cannot be read drops silently otherwise, and
            # "no findings" is indistinguishable from "nothing to find".
            message = f"Could not read {directory}: {exc}"
            if message not in context.lint_tree_errors:
                context.lint_tree_errors.append(message)
            logger.warning(message)
            return []

    def _add_glob(
        parent: LintTarget,
        directory: Path,
        pattern: str,
        block_cls: type,
        skip_dirs: frozenset[str] = frozenset(),
        content_suppressed: bool = False,
    ) -> None:
        """Attach every file matching *pattern* under *directory*.

        *skip_dirs* names immediate subdirectories the owning tool does not
        read, so their contents are not swept in under this block type.
        """
        for match in _readable_matches(directory, pattern):
            # First component only: Cline reserves ``workflows``, ``hooks``
            # and ``skills`` at the top of .clinerules, not everywhere. A
            # rule filed under ``backend/hooks/`` is ordinary prose that
            # Cline does concatenate, and matching at any depth would drop
            # it from the tree entirely rather than merely misfiling it.
            relative = match.relative_to(directory).parts[:-1]
            if skip_dirs and relative and relative[0] in skip_dirs:
                continue
            if safe_is_file(match):
                state.add_block(parent, match, block_cls, content_suppressed=content_suppressed)

    # Cursor reads the legacy file from the nearest enclosing directory too,
    # so a monorepo package keeps its own — discovered in the same walk that
    # finds `.cursor/`, which is what keeps detection and attachment agreeing.
    for legacy_cursor in context.legacy_editor_files(".cursorrules"):
        state.add_block(root, legacy_cursor, InstructionBlock)

    for cursor_dir in context.agent_tool_dirs(".cursor"):
        # APM's cursor target compiles ``.apm/instructions/`` into
        # ``.cursor/rules/`` only (docs/repo-types.md) — not commands, mcp.json
        # or hooks.json, which are authored even in an APM repo. So the compiled
        # flag scopes to ``rules/``: a compiled rule's prose duplicates its
        # ``.apm/`` source and is dropped, but it is attached (not skipped) so
        # the security and structural rules still see a copy that could have
        # been hand-edited. Everything else under ``.cursor/`` is authored and
        # linted in full.
        rules_suppressed = _is_in_compiled_dir(cursor_dir)
        # ``rules/`` nests: Cursor walks it recursively, so category
        # subdirectories are ordinary rule files, not decoration.
        _add_glob(
            root,
            cursor_dir / "rules",
            "**/*.mdc",
            CursorRuleBlock,
            content_suppressed=rules_suppressed,
        )
        _add_glob(root, cursor_dir / "commands", "**/*.md", CursorCommandBlock)
        state.add_parser_block(root, cursor_dir / "mcp.json", CursorMcpBlock)
        _add_project_hooks(state, root, cursor_dir / "hooks.json", CursorHooksBlock)

    for github_dir in context.agent_tool_dirs(".github"):
        # A compiled Copilot copy duplicates its ``.apm/`` source for the
        # content rules, so those findings are dropped — but it is attached,
        # not removed, so the security rules still scan what actually ships.
        copilot_instructions = github_dir / "copilot-instructions.md"
        state.add_block(
            root,
            copilot_instructions,
            InstructionBlock,
            content_suppressed=_is_apm_compiled_github(copilot_instructions),
        )
        # ``.github/instructions/**/*.instructions.md`` needs no entry: the
        # repository scan collects every ``*.instructions.md`` wherever it
        # lives, and they are attached with the root instruction files above.
        for sub, pattern, block_cls in (
            ("prompts", "**/*.prompt.md", CopilotPromptBlock),
            # VS Code detects *any* .md in .github/agents as a custom agent;
            # .agent.md is the recommended convention, not the detection rule.
            ("agents", "**/*.md", CopilotAgentBlock),
            # Chat modes are the pre-2026 spelling of custom agents. VS Code
            # documents renaming them to .agent.md; still linted because the
            # prose ships in the repository either way.
            ("chatmodes", "**/*.chatmode.md", CopilotAgentBlock),
        ):
            directory = github_dir / sub
            _add_glob(
                root,
                directory,
                pattern,
                block_cls,
                content_suppressed=_is_apm_compiled_github(directory),
            )

    for vscode_dir in context.agent_tool_dirs(".vscode"):
        state.add_parser_block(root, vscode_dir / "mcp.json", VsCodeMcpBlock)

    # Codex loads project hooks from the ``.codex/`` layer of the project it
    # is started in, plugin or not — and in a monorepo that is as often a
    # package as the repository root, so a package's own layer is live
    # configuration. The walk-backed lookup finds both, which is also what
    # ``RepositoryType.CODEX_PROJECT`` detection reads: detection agrees with
    # attachment.
    for codex_dir in context.agent_tool_dirs(CODEX_DIR_NAME):
        _add_project_hooks(state, root, codex_dir / CODEX_HOOKS_FILENAME, CodexHooksBlock)
        _add_codex_config(state, root, codex_dir / CODEX_CONFIG_FILENAME)

    for muse_dir in context.agent_tool_dirs(muse.TOOL_DIR_NAME):
        _add_project_hooks(state, root, muse_dir / muse.HOOKS_FILENAME, MuseHooksBlock)

    # Grok Build reads the ``.grok/`` layer of the project it is started in,
    # as Codex does, so a monorepo package's own layer is live configuration
    # and the walk-backed lookup finds both. Every directory here is read
    # *flat* — a nested ``rules/theme/style.md`` or ``commands/git/sync.md``
    # is not loaded, and a recursive glob would budget context Grok never
    # sees. ``skills/`` is the exception and is walked recursively through
    # ``CONVENTIONAL_SKILL_DIRS``, which earns the whole skill rule set.
    # ``plugins/`` is Grok's install location and belongs to its own plugin
    # discovery, so nothing here descends into it.
    for grok_dir in context.agent_tool_dirs(grok.TOOL_DIR_NAME):
        _add_glob(root, grok_dir / grok.RULES_DIR_NAME, "*.md", GrokRuleBlock)
        _add_glob(root, grok_dir / grok.COMMANDS_DIR_NAME, "*.md", GrokCommandBlock)
        _add_glob(root, grok_dir / grok.AGENTS_DIR_NAME, "*.md", GrokAgentBlock)
        # One block per file: Grok merges every ``.json`` in the directory,
        # so a repository has as many hooks blocks as it has files. Through
        # ``_readable_matches`` rather than ``_add_glob`` because each match
        # needs the hooks parser, but with the same containment, exclusion
        # and unreadable-directory guards ``_add_glob`` gets.
        for hooks_file in _readable_matches(grok_dir / grok.HOOKS_DIR_NAME, grok.HOOKS_GLOB):
            _add_project_hooks(state, root, hooks_file, GrokHooksBlock)
        # ``config.toml`` is where a Grok project declares its MCP servers —
        # there is no ``.grok/mcp.json`` — so it is attached under its own
        # parser role rather than as prose, and one block per resolved file.
        state.add_parser_block(root, grok_dir / grok.CONFIG_FILENAME, GrokConfigBlock)

    # Committed project memory: notes a team checks in for whatever agent
    # reads the checkout. The index is loaded whole and every other Markdown
    # file in the directory on demand — which is why the glob below takes
    # them all, index entry or not — so all of it is agent context and gets
    # every content and security rule — unconditionally, because content is
    # content whether or not a reader for it is configured here. One
    # directory, at the root, where the convention puts it.
    memory_dir = context.root_path.joinpath(*AGENT_MEMORY_DIR)
    state.add_block(root, memory_dir / AGENT_MEMORY_INDEX, AgentMemoryIndexBlock)
    _add_glob(root, memory_dir, "**/*.md", AgentMemoryBlock)

    # The skills CLI writes one project lockfile at each project root. A
    # monorepo may therefore have several, all found by the shared walk.
    for lockfile in context.skills_lock_files():
        state.add_parser_block(root, lockfile, SkillsLockBlock)

    def _add_opencode_config(directory: Path) -> None:
        """Attach every ``opencode.json`` and ``opencode.jsonc`` in *directory*.

        Both extensions, under both parser roles.

        One document, two parser roles: the whole file is validated by
        ``opencode-config-valid``, and its ``mcp`` section is additionally
        exposed as an :class:`McpBlock` so the ecosystem-neutral policy and
        security rules read OpenCode's servers the way they read every other
        host's. ``state.add_parser_block`` is role-aware, so this is one file
        appearing twice in the tree rather than two findings for one defect.
        """
        for name in _OPENCODE_CONFIG_NAMES:
            config = state.add_parser_block(root, directory / name, OpenCodeConfigBlock)
            if isinstance(config, OpenCodeConfigBlock):
                state.opencode_configs.append(config)
            state.add_parser_block(root, directory / name, OpenCodeMcpBlock)

    def _add_opencode_instructions() -> None:
        """Attach local files selected by each OpenCode ``instructions`` entry.

        OpenCode treats these paths and globs as ambient instruction text. A
        config under ``.opencode/`` belongs to the directory containing that
        tool directory; a root config belongs to the repository root. Remote
        URLs are deliberately left alone: lint-tree construction never opens
        a connection, and the local checkout contains no stable content to
        inspect for them.

        This runs after every ordinary content attachment. A configured glob
        may select a skill, command, editor rule, or OpenCode agent, and its
        structural owner must claim it before path-only content deduplication.
        """
        searched: Set[Tuple[Path, str]] = set()
        searches: List[Tuple[Path, str]] = []
        for config in state.opencode_configs:
            data = config.raw_data
            instructions = data.get("instructions") if data is not None else None
            if not isinstance(instructions, list):
                continue
            project_dir = (
                config.path.parent.parent
                if config.path.parent.name == ".opencode"
                else config.path.parent
            )
            if state.resolve_repo_path(project_dir) is None:
                continue
            search_dirs: List[Path] = []
            current = project_dir
            while True:
                search_dirs.append(current)
                if current == context.root_path:
                    break
                parent = current.parent
                if parent == current or state.resolve_repo_path(parent) is None:
                    break
                current = parent

            for raw_pattern in instructions:
                if (
                    not isinstance(raw_pattern, str)
                    or raw_pattern.startswith(("https://", "http://", "~/"))
                    or has_parent_traversal(raw_pattern)
                ):
                    continue

                pattern_path = Path(raw_pattern)
                if is_absolute_path(raw_pattern):
                    # On the current host only POSIX absolute paths can name
                    # a file in this checkout. A Windows-rooted value is an
                    # external path here and therefore has no lintable local
                    # content.
                    if not pattern_path.is_absolute():
                        continue
                    candidates = ((pattern_path.parent, pattern_path.name),)
                else:
                    candidates = tuple((base, raw_pattern) for base in search_dirs)

                for glob_base, pattern in candidates:
                    resolved_base = state.resolve_repo_path(glob_base)
                    search = (resolved_base, pattern) if resolved_base is not None else None
                    if search is None or search in searched or not safe_is_dir(glob_base):
                        continue
                    searched.add(search)
                    searches.append((glob_base, pattern))

        searches_by_base: Dict[Path, List[Tuple[int, str]]] = {}
        for search_index, (glob_base, pattern) in enumerate(searches):
            searches_by_base.setdefault(glob_base, []).append((search_index, pattern))

        matches_by_search: List[List[Path]] = [[] for _search in searches]
        for glob_base, ranked_patterns in searches_by_base.items():
            patterns = [pattern for _rank, pattern in ranked_patterns]
            try:
                for pattern_index, match in contained_instruction_globs(
                    repo_root,
                    glob_base,
                    patterns,
                    _is_excluded,
                ):
                    search_index = ranked_patterns[pattern_index][0]
                    matches_by_search[search_index].append(match)
            except (OSError, ValueError):
                # OpenCode also ignores invalid patterns. The config rule owns
                # schema/type diagnostics; discovery stays best-effort.
                continue

        for matches in matches_by_search:
            for match in matches:
                resolved_match = state.resolve_repo_path(match)
                if resolved_match is not None and safe_is_file(resolved_match):
                    state.add_block(
                        root,
                        match,
                        _instruction_block_type(match),
                        content_suppressed=_is_in_compiled_dir(match),
                    )

    # The project config is read from the repository root as well as from
    # ``.opencode/``. The root copy is never APM output — APM compiles into
    # ``.opencode/``, never over a root config — so it is attached
    # unconditionally.
    _add_opencode_config(context.root_path)

    _opencode_blocks = {
        "OpenCodeCommandBlock": OpenCodeCommandBlock,
        "OpenCodeAgentBlock": OpenCodeAgentBlock,
    }
    for opencode_dir in context.agent_tool_dirs(".opencode"):
        # When APM compiles the ``opencode`` target it owns this whole
        # directory, so its prose duplicates the ``.apm/`` sources the author
        # actually edits and the content findings belong there. The copy is
        # still attached, not skipped, so the security and structural rules
        # read what really ships — a generated file can be hand-edited.
        compiled = _is_in_compiled_dir(opencode_dir)
        for sub, pattern, block_name in _OPENCODE_CONTENT_DIRS:
            _add_glob(
                root,
                opencode_dir / sub,
                pattern,
                _opencode_blocks[block_name],
                content_suppressed=compiled,
            )
        _add_opencode_config(opencode_dir)

    for dir_name in devin.TOOL_DIR_NAMES:
        for devin_dir in context.agent_tool_dirs(dir_name):
            _add_glob(root, devin_dir / "rules", "**/*.md", DevinRuleBlock)
            state.add_block(root, devin_dir / "global_rules.md", DevinGlobalRuleBlock)

    kiro_steering = context.root_path / ".kiro" / "steering"
    if kiro_steering.is_dir():
        for md in sorted(kiro_steering.glob("*.md")):
            state.add_block(root, md, InstructionBlock)

    state.add_block(root, context.root_path / ".windsurfrules", InstructionBlock)

    # Same story as `.cursorrules`: the file form of `.clinerules` is read
    # from the workspace directory, so a package that carries its own is
    # linted alongside the root's.
    for clinerules_file in context.legacy_editor_files(".clinerules"):
        state.add_block(root, clinerules_file, InstructionBlock)
    for clinerules_dir in context.agent_tool_dirs(".clinerules"):
        # Cline concatenates every .md and .txt under .clinerules/ into the
        # system prompt, but its loader excludes three subdirectories:
        # workflows/ (on demand), skills/ (on demand, and discovered as
        # skills), and hooks/ (executables, not prose). Sweeping them in
        # would budget content Cline never loads as always-on context.
        # Claim the workflows first: ``state.add_block`` keeps the first role a
        # path gets.
        _add_glob(root, clinerules_dir / "workflows", "**/*.md", ClineWorkflowBlock)
        for pattern in ("**/*.md", "**/*.txt"):
            _add_glob(
                root,
                clinerules_dir,
                pattern,
                InstructionBlock,
                skip_dirs=_CLINE_EXCLUDED_DIRS,
            )

    # --- Marketplace config ---
    marketplace_json = context.root_path / ".claude-plugin" / "marketplace.json"
    if marketplace_json.exists() and not _is_excluded(marketplace_json):
        root.children.append(MarketplaceConfigNode(path=marketplace_json))

    # --- Codex marketplace configs ---
    # Not filtered by _is_in_compiled_dir even though ".agents" is an APM
    # compiled root: APM generates .agents/skills/ and friends, never
    # .agents/plugins/marketplace.json, which is hand-authored.
    for codex_marketplace_json in context.codex_marketplace_paths():
        if not _is_excluded(codex_marketplace_json):
            root.children.append(CodexMarketplaceConfigNode(path=codex_marketplace_json))

    # --- Grok marketplace configs ---
    # The optional plugin-index.json hangs off its catalog rather than off
    # the tree root: a parity check needs the pair, and the child edge is
    # what supplies it without a second filesystem probe. An index with no
    # catalog beside it attaches nowhere, which is right — it is a display
    # catalog for a marketplace, and on its own there is nothing to drift
    # from.
    for grok_marketplace_json in context.grok_marketplace_paths():
        if _is_excluded(grok_marketplace_json):
            continue
        catalog_node = GrokMarketplaceConfigNode(path=grok_marketplace_json)
        marketplace_root = safe_resolve(grok_marketplace_json.parent.parent)
        if marketplace_root is not None:
            index_locations = [(grok_marketplace_json.parent / grok.PLUGIN_INDEX_FILENAME, False)]
            # An index at a fallback catalog location is a file Grok never
            # reads, and the parity rule reports it — so it is a node here
            # like every other file the rules report on, rather than a probe
            # of its own from inside the rule.
            index_locations.extend(
                (marketplace_root.joinpath(*parts, grok.PLUGIN_INDEX_FILENAME), True)
                for parts in grok.UNREAD_INDEX_DIRS
            )
            # These attach straight onto the catalog node rather than
            # through ``add_parser_block``, so nothing else deduplicates
            # them: a stray location symlinked at the conventional one is
            # one file, and a second node would report it twice.
            index_seen: set[Path] = set()
            for index_json, stray in index_locations:
                # Contained against the marketplace root, the boundary the
                # catalog's own sources are held to: an index symlinked out
                # of the marketplace is not this marketplace's display
                # catalog, and the parity rule would report a file it does
                # not own.
                resolved_index = contained_resolve(index_json, marketplace_root)
                if resolved_index is None or resolved_index in index_seen:
                    continue
                if safe_is_file(index_json) and not _is_excluded(index_json):
                    index_seen.add(resolved_index)
                    catalog_node.children.append(
                        GrokMarketplaceIndexNode(path=index_json, stray=stray)
                    )
        root.children.append(catalog_node)

    # --- Plugins (build first so skills can nest inside them) ---
    plugin_nodes: dict[Path, PluginNode] = {}
    codex_plugin_nodes: dict[Path, CodexPluginNode] = {}
    grok_plugin_nodes: dict[Path, GrokPluginNode] = {}
    agent_plugin_nodes: dict[Path, AgentPluginNode] = {}
    marketplace_dir = context.root_path / "plugins"
    marketplace_node: MarketplaceNode | None = None
    if (context.has_marketplace() or context.has_codex_marketplace()) and marketplace_dir.is_dir():
        marketplace_node = MarketplaceNode(path=marketplace_dir)
        root.children.append(marketplace_node)

    # --- Plugins: one pass over every claimed directory ---
    # Exactly one container per directory, with prose and config attached
    # from its provenance. Never add per-ecosystem loops: two loops that
    # must complement each other exactly are how a directory falls between
    # attach paths and loses its content silently.
    plugin_dirs: list[Path] = []
    seen_plugin_dirs: set[Path] = set()
    # Catalog claims join the union: a local source with no manifest and no
    # legacy marker is still a claimed directory whose hooks, prose, and
    # skills the rules must see. The claim set is resolved and contained
    # already.
    for candidate in (
        *context.plugins,
        *context.codex_plugins,
        *context.grok_plugins,
        *context.agent_plugins,
        *sorted(p for p in context._codex_claim_set() if not context.is_path_excluded(p)),
        *sorted(p for p in context._grok_claim_set() if not context.is_path_excluded(p)),
        *sorted(p for p in context._agent_plugin_claim_set() if not context.is_path_excluded(p)),
    ):
        resolved_candidate = safe_resolve(candidate)
        if resolved_candidate is None:
            # A claim that cannot resolve (symlink loop, unreadable
            # parent) must not abort tree construction for the whole
            # repository.
            continue
        if resolved_candidate in seen_plugin_dirs:
            continue
        if not safe_is_dir(candidate):
            # A dangling catalog claim names no directory to lint;
            # codex-marketplace-registration reports the entry itself.
            continue
        seen_plugin_dirs.add(resolved_candidate)
        plugin_dirs.append(candidate)

    root_plugin_owner: Path | None = None
    for plugin_path in plugin_dirs:
        prov = context.provenance(plugin_path)
        # Compiled-output filtering is a Claude/APM concept; a Codex claim
        # is its own provenance and keeps the directory.
        if _is_in_compiled_dir(plugin_path) and not prov.codex:
            continue
        resolved_plugin = safe_resolve(plugin_path)
        if resolved_plugin is None:
            continue

        is_agent_plugin = resolved_plugin in agent_plugin_roots
        agent_plugin_mcp = safe_resolve(plugin_path / "mcp.json") if is_agent_plugin else None

        # Container type: Claude identity keeps PluginNode and its Claude
        # rules. Otherwise Codex wins the neutral hierarchy choice when a
        # package declares both non-Claude formats; each format still gets
        # its own config node below the one shared container. Root packages
        # hang directly off the tree root.
        container: LintTarget
        if prov.claude:
            container = PluginNode(path=plugin_path)
            plugin_nodes[resolved_plugin] = container
        elif resolved_plugin == root.resolved_path and (prov.codex or prov.grok or is_agent_plugin):
            container = root
        elif prov.codex:
            container = CodexPluginNode(path=plugin_path)
            codex_plugin_nodes[resolved_plugin] = container
        elif prov.grok:
            container = GrokPluginNode(path=plugin_path)
            grok_plugin_nodes[resolved_plugin] = container
        elif is_agent_plugin:
            container = AgentPluginNode(path=plugin_path)
            agent_plugin_nodes[resolved_plugin] = container
        else:
            # Legacy unclaimed directories discovered by the Claude layout
            # retain their established container and validation behavior.
            container = PluginNode(path=plugin_path)
            plugin_nodes[resolved_plugin] = container

        if container is not root:
            container.plugin_owner = resolved_plugin
        else:
            # A repo-root package shares conventional config paths with the
            # repository, so ownership is decided here once.
            root_plugin_owner = resolved_plugin
            # ``.mcp.json`` and the project layer's ``.codex/hooks.json``
            # need re-tagging. The generic root attach runs first and adds
            # them untagged, and for a repo-root plugin that project layer
            # is the plugin's own — but no manifest names either file, so
            # nothing downstream claims them and this is the only place the
            # owner can be recorded. A hooks file the manifest *does*
            # declare needs nothing here: ``_claim_attached_hooks`` tags it
            # in the declared-files loop below, wherever the plugin sits in
            # the tree. (``hooks/hooks.json`` needs nothing either: it
            # attaches under the Codex cluster with containment.)
            claimed_mcp = {safe_resolve(plugin_path / ".mcp.json")} - {None}
            claimed_hooks: Set[Optional[Path]] = set()
            if prov.codex:
                claimed_hooks = {
                    safe_resolve(plugin_path / CODEX_DIR_NAME / CODEX_HOOKS_FILENAME)
                } - {None}
            for child in root.children:
                if isinstance(child, McpBlock) and safe_resolve(child.path) in claimed_mcp:
                    child.plugin_owner = resolved_plugin
                elif isinstance(child, HooksBlock) and safe_resolve(child.path) in claimed_hooks:
                    child.plugin_owner = resolved_plugin

        _add_plugin_prose(container, plugin_path, resolved_plugin)

        # Conventional Claude configs belong only to Claude or legacy
        # unclaimed packages. Portable-only packages must not accidentally
        # inherit Claude's hooks, .mcp.json, or settings semantics.
        if prov.claude or (not prov.ecosystems and not is_agent_plugin):
            state.add_block(
                container,
                plugin_path / "hooks" / "hooks.json",
                ClaudeHooksBlock,
                owner=resolved_plugin,
            )
            native_mcp = plugin_path / ".mcp.json"
            if not _shadowed_by_agent_plugin_mcp(native_mcp, agent_plugin_mcp):
                state.add_block(container, native_mcp, McpBlock, owner=resolved_plugin)
        # settings.json is Claude-side configuration with no Codex
        # counterpart: attached only for Claude-style directories, keeping
        # the generic attachment path away from content a hostile
        # Codex-only checkout controls.
        if prov.claude or (not prov.ecosystems and not is_agent_plugin):
            state.add_block(
                container, plugin_path / "settings.json", SettingsBlock, owner=resolved_plugin
            )
            state.add_block(
                container, plugin_path / "settings.local.json", SettingsBlock, owner=resolved_plugin
            )

        # Codex manifest cluster, for any directory Codex claims (dual
        # directories hang it off their PluginNode).
        if prov.codex:
            manifest = plugin_path.joinpath(*context.CODEX_PLUGIN_MANIFEST)
            # Not gated on the manifest existing: a plugin whose manifest is
            # missing must still reach codex-plugin-json-valid to be
            # reported. An excluded manifest is no plugin-wide skip either —
            # hooks and MCP files carry executable commands and have their
            # own exclusion checks; the linter filters violations filed
            # against the excluded manifest itself.
            node = CodexPluginConfigNode(path=manifest)
            node.plugin_owner = resolved_plugin
            state.add_openai_metadata(
                node,
                plugin_path / "agents" / "openai.yaml",
                metadata_root=plugin_path,
                containment_root=plugin_path,
            )
            # Codex "checks that default file automatically", so a plugin
            # can ship executable hooks without declaring them — the same
            # supply-chain surface as a Claude plugin's hooks.
            #
            # Typed by provenance, because the block class picks the shape
            # rule. Only Codex reads a Codex-only plugin's hooks, so they
            # are ``codex-hooks-valid``'s. A dual-manifest plugin's
            # conventional file is read by both hosts and keeps the Claude
            # block the Claude branch attached above: one block per file, so
            # the security rules report each command once, and Claude's
            # results for it stand (``TestDualManifestBackwardCompat``).
            hooks_cls = CodexHooksBlock if prov.codex_only else ClaudeHooksBlock
            _add_contained_plugin_block(
                node, plugin_path / "hooks" / "hooks.json", hooks_cls, owner=resolved_plugin
            )
            # A manifest may point ``hooks`` at other files, or write them
            # inline; both carry the same executable commands. Inline
            # payloads have no file of their own, so they borrow the
            # manifest path — and only Codex reads that manifest, so they
            # are Codex's whatever else claims the directory.
            #
            # A declared file is Codex's for the same reason: nothing but the
            # Codex manifest names it, so no other host loads it, even in a
            # dual-manifest plugin whose conventional ``hooks/hooks.json``
            # stayed Claude's above. The exception is a file some earlier
            # attach already put in the tree as hooks — that same
            # conventional file when the manifest also declares it, the
            # project layer's ``.codex/hooks.json``, or another tool's file
            # a manifest points at. That block is claimed rather than
            # re-attached: one block per file, or the security rules report
            # every command in it twice, but the declaration is still what
            # tells ``skillsaw docs`` whose hooks those are.
            for declared_hooks in codex_declared_hook_files(plugin_path):
                if _claim_attached_hooks(state, root, declared_hooks, resolved_plugin):
                    continue
                state.add_parser_block(node, declared_hooks, CodexHooksBlock, owner=resolved_plugin)
            for inline_hooks in codex_inline_hooks(plugin_path):
                inline_block = CodexInlineHooksBlock(path=manifest, inline_data=inline_hooks)
                inline_block.plugin_owner = resolved_plugin
                node.children.append(inline_block)
            # Same treatment for MCP: the conventional .mcp.json, declared
            # files, and inline maps are all commands the host will spawn.
            native_mcp = plugin_path / ".mcp.json"
            if not _shadowed_by_agent_plugin_mcp(native_mcp, agent_plugin_mcp):
                _add_contained_plugin_block(node, native_mcp, McpBlock, owner=resolved_plugin)
            for declared_mcp in codex_declared_mcp_files(plugin_path):
                if _shadowed_by_agent_plugin_mcp(declared_mcp, agent_plugin_mcp):
                    continue
                state.add_parser_block(node, declared_mcp, McpBlock, owner=resolved_plugin)
            for inline_mcp in codex_inline_mcp_servers(plugin_path):
                inline_block = CodexInlineMcpBlock(path=manifest, inline_data=inline_mcp)
                inline_block.plugin_owner = resolved_plugin
                node.children.append(inline_block)
            container.children.append(node)

        # Grok manifest cluster, for any directory Grok claims (dual
        # directories hang it off their PluginNode). Not gated on the
        # manifest existing: Grok treats one as optional, so a claimed
        # directory without one is a plugin whose components come from the
        # conventional paths, and the node is what a manifest rule reads.
        if prov.grok:
            manifest = grok.grok_manifest_path(plugin_path) or plugin_path.joinpath(
                grok.PLUGIN_DIR_NAME, grok.PLUGIN_MANIFEST
            )
            node = GrokPluginConfigNode(path=manifest)
            node.plugin_owner = resolved_plugin
            # A manifest may point ``commands`` or ``agents`` at directories
            # of its own naming, and Grok then loads those *instead of* the
            # conventional pair — measured, the same replacement it applies
            # to ``skills``. ``_add_plugin_prose`` attached the conventional
            # pair above; these are the files that actually load, and they
            # need the same content, frontmatter, security and routing
            # checks. Read flat, as the conventional attach reads them, and
            # deduplicated by ``add_block``, so a manifest naming the
            # conventional directory attaches nothing twice.
            for field_name, prose_cls in (("commands", CommandBlock), ("agents", AgentBlock)):
                for declared_dir in grok.grok_declared_paths(
                    plugin_path, field_name, want_dir=True
                ):
                    try:
                        declared_prose = sorted(declared_dir.glob("*.md"))
                    except OSError:
                        continue
                    for md in declared_prose:
                        # The same predicate the conventional attach uses:
                        # inside the plugin, and not inside a nested claimed
                        # one — a manifest may point the field at a
                        # directory that holds another plugin.
                        if _inside_plugin(md, resolved_plugin):
                            state.add_block(container, md, prose_cls, owner=resolved_plugin)
            # Whichever host already reads the *conventional* files keeps
            # its block class: one block per file, or the security rules
            # report every command in it twice, and a dual-manifest plugin's
            # established Claude results have to stand.
            if prov.claude:
                hooks_cls, mcp_cls = ClaudeHooksBlock, McpBlock
            elif prov.codex:
                hooks_cls, mcp_cls = CodexHooksBlock, McpBlock
            else:
                hooks_cls, mcp_cls = GrokPluginHooksBlock, GrokMcpBlock
            # Grok discovers ``hooks/hooks.json`` and ``.mcp.json`` with no
            # manifest at all, so a plugin ships executable hooks and
            # spawnable servers without declaring either. Plugin hooks get
            # ``GrokPluginHooksBlock`` rather than the project layer's
            # class: Grok loads them through a different adapter whose
            # per-entry failure scope 1.0.13 publishes no observable for, so
            # ``grok-hooks-valid``'s measured verdicts do not cover them.
            conventional_hooks = plugin_path / "hooks" / "hooks.json"
            if not _attached_as_hooks(state, conventional_hooks):
                # Guarded where the Codex cluster is not: Codex's project and
                # plugin files share one class, so ``add_parser_block``'s
                # ``(path, block_cls)`` role key dedupes them. Grok's plugin
                # class is a sibling of the project layer's, so a plugin file
                # symlinked to a ``.grok/hooks/*.json`` would arrive twice and
                # the security rules would report every command in it twice.
                _add_contained_plugin_block(
                    node, conventional_hooks, hooks_cls, owner=resolved_plugin
                )
            # A declared file is Grok's whatever else claims the directory:
            # only the Grok manifest names it, so no other host loads it,
            # and it must not arrive under a class whose shape rule was
            # measured on another host's files. The conventional file both
            # hosts read is the exception, and it is already attached above
            # — ``_claim_attached_hooks`` finds it and records the
            # declaration rather than adding a second block.
            for declared_hooks in grok.grok_declared_hook_files(plugin_path):
                # The same predicate the declared prose above uses: a
                # manifest may name a file inside a nested claimed plugin,
                # and claiming it here would take it from the plugin that
                # ships it — ``_attached_as_hooks`` then suppresses the
                # nested attach and the file arrives under the wrong owner.
                if not _inside_plugin(declared_hooks, resolved_plugin):
                    continue
                if _claim_attached_hooks(state, root, declared_hooks, resolved_plugin):
                    continue
                state.add_parser_block(
                    node, declared_hooks, GrokPluginHooksBlock, owner=resolved_plugin
                )
            for inline_hooks in grok.grok_inline_hooks(plugin_path):
                inline_hooks_block = GrokInlineHooksBlock(path=manifest, inline_data=inline_hooks)
                inline_hooks_block.plugin_owner = resolved_plugin
                node.children.append(inline_hooks_block)
            native_mcp = plugin_path / ".mcp.json"
            if not (
                _shadowed_by_agent_plugin_mcp(native_mcp, agent_plugin_mcp)
                or _attached_as_mcp(state, native_mcp)
            ):
                _add_contained_plugin_block(node, native_mcp, mcp_cls, owner=resolved_plugin)
            for declared_mcp in grok.grok_declared_mcp_files(plugin_path):
                if not _inside_plugin(declared_mcp, resolved_plugin):
                    continue
                if _shadowed_by_agent_plugin_mcp(
                    declared_mcp, agent_plugin_mcp
                ) or _attached_as_mcp(state, declared_mcp):
                    continue
                # Grok's own class, whatever else claims the directory —
                # the same reasoning as the declared hooks above: only the
                # Grok manifest names this file, so no other host loads it.
                state.add_parser_block(node, declared_mcp, GrokMcpBlock, owner=resolved_plugin)
            for inline_mcp in grok.grok_inline_mcp(plugin_path):
                inline_mcp_block = GrokInlineMcpBlock(path=manifest, inline_data=inline_mcp)
                inline_mcp_block.plugin_owner = resolved_plugin
                node.children.append(inline_mcp_block)
            container.children.append(node)

        # Agent Plugins manifest cluster. A forced ``--type agent-plugin``
        # seeds this even when plugin.json is absent, so the validity rule can
        # report the missing entrypoint. The optional mcp.json is attached
        # only when it is a contained regular file; malformed path/kind cases
        # remain visible to the config rule through the manifest node.
        if is_agent_plugin:
            node = AgentPluginConfigNode(path=plugin_path / "plugin.json")
            node.plugin_owner = resolved_plugin
            _add_contained_plugin_block(
                node,
                plugin_path / "mcp.json",
                AgentPluginMcpBlock,
                owner=resolved_plugin,
            )
            container.children.append(node)

        if container is not root:
            if marketplace_node is not None and resolved_plugin.is_relative_to(
                (safe_resolve(marketplace_dir) or marketplace_dir)
            ):
                marketplace_node.children.append(container)
            else:
                root.children.append(container)

    # --- Skills (nest inside parent plugin when applicable; skip .apm/) ---
    for skill_path in context.skills:
        if _is_in_apm_source(skill_path):
            continue
        native_devin = devin.is_devin_native_skill_dir(skill_path)
        skill_node = DevinSkillNode(path=skill_path) if native_devin else SkillNode(path=skill_path)
        block_cls = DevinSkillBlock if native_devin else SkillBlock
        state.add_block(skill_node, skill_path / "SKILL.md", block_cls)
        # Contained against the owning package: rules both read and
        # rewrite these files, so a symlink here is a read *and* a write
        # outside the checkout.
        ref_root = _contained_plugin_owner(skill_path)

        state.add_openai_metadata(
            skill_node,
            skill_path / "agents" / "openai.yaml",
            metadata_root=skill_path,
            containment_root=ref_root or skill_path,
        )

        def _contained_in_plugin(candidate: Path, ref_root: Path | None = ref_root) -> bool:
            if ref_root is None:
                return True
            resolved = safe_resolve(candidate)
            return resolved is not None and resolved.is_relative_to(ref_root)

        refs_dir = skill_path / "references"
        if refs_dir.is_dir():
            for ref_file in sorted(refs_dir.glob("*.md")):
                if _contained_in_plugin(ref_file):
                    state.add_block(skill_node, ref_file, SkillRefBlock)

        # Nearest plugin ancestor via dict lookups — iterating all plugins
        # with is_relative_to() is O(skills x plugins) and dominated tree
        # construction on large marketplaces (3.6k skills x 445 plugins).
        parent_plugin: LintTarget | None = None
        resolved_skill = safe_resolve(skill_path) or skill_path
        for candidate in (resolved_skill, *resolved_skill.parents):
            node = (
                plugin_nodes.get(candidate)
                or codex_plugin_nodes.get(candidate)
                or grok_plugin_nodes.get(candidate)
                or agent_plugin_nodes.get(candidate)
            )
            if node is not None:
                parent_plugin = node
                skill_node.plugin_owner = candidate
                break
        if parent_plugin is not None:
            parent_plugin.children.append(skill_node)
        else:
            # A repo-root package has no container of its own, so its
            # skills hang off the tree root; the ownership tag keeps them
            # attributable to the plugin all the same.
            skill_node.plugin_owner = root_plugin_owner
            root.children.append(skill_node)

    # --- .coderabbit.yaml ---
    cr_path = context.root_path / ".coderabbit.yaml"
    cr_resolved = state.resolve_repo_path(cr_path)
    if cr_resolved is not None and safe_exists(cr_resolved) and not _is_excluded(cr_path):
        cr_container = CodeRabbitNode(path=cr_path)
        cr_blocks = CodeRabbitContentBlock.gather(context, state.seen, _is_excluded)
        cr_container.children.extend(cr_blocks)
        root.children.append(cr_container)

    # --- Promptfoo eval configs ---
    _build_promptfoo_nodes(context, root, plugin_nodes, state.seen, _is_excluded)

    # --- Cursor prompt-hook content blocks ---
    # Attached to the root rather than to the hooks block: a JsonConfigBlock
    # is a leaf, and hanging prose off it would put content blocks inside the
    # config half of the hierarchy.
    root.children.extend(CursorPromptHookBlock.gather_from_tree(root))

    # --- Promptfoo prompt content blocks ---
    for block in PromptfooPromptBlock.gather_from_tree(root):
        block_resolved = safe_resolve(block.path) or block.path
        for node in root.find(PromptfooConfigNode):
            if (safe_resolve(node.path) or node.path) == block_resolved:
                node.children.append(block)
                break

    # --- APM ---
    _attach_apm_tree(state)

    # --- Extra content paths from config ---
    # User-configured content paths plus globs contributed by detected
    # plugin repo types; the ``seen`` set dedupes any overlap.
    for glob_pattern in [*context.content_paths, *context.plugin_content_paths]:
        try:
            matches = sorted(context.root_path.glob(glob_pattern))
        except (NotImplementedError, ValueError) as e:
            # Path.glob() rejects absolute patterns (NotImplementedError)
            # and some malformed ones (ValueError). The tree builds lazily
            # inside each rule's check(), so an invalid pattern — from user
            # config ``content-paths`` or a plugin repo type — would
            # otherwise surface as one rule-execution-error per rule.
            logger.warning("Ignoring invalid content path glob %r: %s", glob_pattern, e)
            continue
        for extra in matches:
            if not extra.is_file():
                continue
            extra_resolved = safe_resolve(extra)
            if extra_resolved is not None and any(
                claimed == extra_resolved for claimed, _ in state.seen_roles
            ):
                # Already attached under a structured parser role (hooks,
                # MCP): re-attaching it as prose would make every
                # content-quality rule lint structured config as text.
                continue
            state.add_block(root, extra, ExtraBlock)

    # --- Plugin tree contributors ---
    # Contributors return pre-constructed nodes (typically ContentBlock or
    # JsonConfigBlock subclasses), attached at the root. The ``seen`` set
    # guards against double-linting files already discovered above, and
    # failures are collected for the Linter to surface as violations —
    # a broken contributor must not abort tree construction.
    def _admit_contributed_node(block) -> bool:
        """Validate/dedupe a contributed node and its whole subtree.

        Contributors may return nodes with children; every descendant gets
        the same guards as top-level discovery (type check, ``seen`` dedupe,
        exclude patterns), with rejected descendants pruned in place.
        Returns False when the node itself must not be attached.
        """
        if not isinstance(block, LintTarget):
            raise TypeError(f"contributor returned {block!r}, which is not a lint tree node")
        if not isinstance(block.path, Path):
            raise TypeError(f"contributor returned a node with invalid path {block.path!r}")
        resolved = state.resolve_repo_path(block.path)
        if resolved is None:
            raise ValueError(f"contributor path is unresolved or outside repository: {block.path}")
        if resolved in state.seen or not safe_exists(resolved) or _is_excluded(block.path):
            return False
        state.seen.add(resolved)
        block.children = [child for child in block.children if _admit_contributed_node(child)]
        return True

    for plugin_name, contribute in context.plugin_tree_contributors:
        try:
            contributed = contribute(context, root)
            blocks = list(contributed) if contributed is not None else []
            # Attachment stays inside the try: a node with a broken path
            # (None, or resolve() raising an OSError) must be reported like
            # any other contributor failure, not crash tree construction.
            for block in blocks:
                if _admit_contributed_node(block):
                    root.children.append(block)
        except Exception as e:
            context.plugin_extension_errors.append(
                f"Plugin '{plugin_name}': tree contributor failed: " f"{e.__class__.__name__}: {e}"
            )
            continue

    # Configured OpenCode instructions are ambient prose, but their
    # original semantic owner wins when a path is also a skill, command,
    # agent, editor rule, README, or plugin-contributed content block.
    _add_opencode_instructions()

    external_roots = context.externally_sourced_roots()

    def _path_is_external(path: Path) -> bool:
        if not external_roots:
            return False
        resolved = safe_resolve(path)
        return resolved is not None and path_within_roots(resolved, external_roots)

    def _tag_and_prune_external(parent: LintTarget, inherited_external: bool = False) -> None:
        """Apply the repository's external-content boundary to every node.

        Centralizing this after builtin and plugin contributors finish means
        a new content type only needs to carry a path (or set the generic tag
        itself). It cannot accidentally bypass reporting policy or autofix by
        forgetting a type-specific guard in its attachment loop.
        """
        kept: list[LintTarget] = []
        for child in parent.children:
            child.externally_sourced = (
                child.externally_sourced or inherited_external or _path_is_external(child.path)
            )
            if child.externally_sourced and not context.lint_external_content:
                continue
            _tag_and_prune_external(child, child.externally_sourced)
            kept.append(child)
        parent.children = kept

    root.externally_sourced = root.externally_sourced or context.is_externally_sourced(
        context.root_path
    )
    _tag_and_prune_external(root, root.externally_sourced)
    root.set_parents()
    nodes = list(root.walk())
    logger.info("Built lint tree: %d nodes", len(nodes))
    return root


def build_lint_tree_safe(context: "RepositoryContext") -> LintTarget:
    """Build once, converting a fatal tree failure into a cached diagnostic."""
    try:
        return build_lint_tree(context)
    except Exception as exc:
        context.lint_tree_errors.append(
            "Failed to build repository lint tree: "
            f"{exc.__class__.__name__}: {safe_display(exc)}"
        )
        root = LintTarget(context.root_path)
        root.set_parents()
        return root


def _build_promptfoo_nodes(
    context: "RepositoryContext",
    root: LintTarget,
    plugin_nodes: dict,
    seen: Set[Path],
    _is_excluded,
) -> None:
    """Discover promptfoo config files and build PromptfooConfigNode nodes.

    Pass 1: find confirmed configs (promptfooconfig* naming or evals/ with promptfoo keys).
    Pass 2: resolve file:// refs from confirmed configs and add fragments as children.
    """
    from .utils import read_yaml

    config_nodes: list[PromptfooConfigNode] = []
    repo_root = safe_resolve(context.root_path)

    def _try_add_config(yaml_file: Path, parent: LintTarget, *, require_keys: bool = True) -> None:
        """Add a contained Promptfoo config that satisfies discovery rules."""
        resolved = contained_resolve(yaml_file, repo_root) if repo_root is not None else None
        if (
            resolved is None
            or resolved in seen
            or not safe_is_file(resolved)
            or _is_excluded(yaml_file)
        ):
            return
        if require_keys:
            data, error = read_yaml(resolved)
            if error or not is_promptfoo_config(data):
                return
        seen.add(resolved)
        node = PromptfooConfigNode(path=yaml_file)
        parent.children.append(node)
        config_nodes.append(node)

    def _scan_evals_dir(evals_dir: Path, parent: LintTarget) -> None:
        for yaml_file in context.promptfoo_eval_files(evals_dir):
            _try_add_config(yaml_file, parent, require_keys=True)

    # Pass 1a: promptfooconfig* anywhere in repo (naming convention → no key
    # check), reusing candidates from the repository's shared discovery walk.
    for yaml_file in context.promptfoo_named_files():
        _try_add_config(yaml_file, root, require_keys=False)

    # Pass 1b: evals/ at repo root
    _scan_evals_dir(context.root_path / "evals", root)

    # Pass 1c: evals/ inside plugins and skills
    for node in list(root.walk()):
        if not isinstance(node, (PluginNode, SkillNode)):
            continue
        _scan_evals_dir(node.path / "evals", node)

    # Pass 2: resolve file:// refs from confirmed configs → fragment children
    for config_node in config_nodes:
        data, error = read_yaml(config_node.path)
        if error or not isinstance(data, dict):
            continue
        config_dir = config_node.path.parent
        for ref in extract_file_refs(data):
            resolved = resolve_file_ref(ref, config_dir, root=context.root_path)
            if resolved is None or resolved in seen:
                continue
            if not safe_exists(resolved) or _is_excluded(Path(resolved)):
                continue
            seen.add(resolved)
            frag = PromptfooConfigNode(path=Path(resolved), is_fragment=True)
            config_node.children.append(frag)

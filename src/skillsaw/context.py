"""
Repository context detection and management
"""

from __future__ import annotations

import fnmatch
from enum import Enum
from pathlib import Path
from typing import Optional, List, Dict, Any, Set
import json
import logging
import os

logger = logging.getLogger(__name__)


class RepositoryType(Enum):
    """Type of repository"""

    SINGLE_PLUGIN = "single-plugin"  # Single plugin at repo root
    MARKETPLACE = "marketplace"  # Marketplace with multiple plugins
    AGENTSKILLS = "agentskills"  # agentskills.io skill repo
    DOT_CLAUDE = "dot-claude"  # .claude/ directory with commands, skills, hooks, etc.
    CODERABBIT = "coderabbit"  # Repository with .coderabbit.yaml
    APM = "apm"  # Repository with .apm/ directory (Agent Package Manager)
    UNKNOWN = "unknown"  # Not a recognized repo type


HAS_CURSOR = "HAS_CURSOR"
HAS_COPILOT = "HAS_COPILOT"
HAS_GEMINI = "HAS_GEMINI"
HAS_AGENTS_MD = "HAS_AGENTS_MD"
HAS_KIRO = "HAS_KIRO"
HAS_CLAUDE_MD = "HAS_CLAUDE_MD"
HAS_CODERABBIT = "HAS_CODERABBIT"
ALL_INSTRUCTION_FORMATS = frozenset(
    {
        HAS_CURSOR,
        HAS_COPILOT,
        HAS_GEMINI,
        HAS_AGENTS_MD,
        HAS_KIRO,
        HAS_CLAUDE_MD,
        HAS_CODERABBIT,
    }
)


class RepositoryContext:
    """
    Context information about the repository being linted

    Automatically detects repository type and gathers relevant metadata.
    """

    _INSTRUCTION_FILENAMES = ("AGENTS.md", "CLAUDE.md", "GEMINI.md")

    _TYPE_PRIORITY = [
        RepositoryType.MARKETPLACE,
        RepositoryType.SINGLE_PLUGIN,
        RepositoryType.APM,
        RepositoryType.DOT_CLAUDE,
        RepositoryType.AGENTSKILLS,
        RepositoryType.CODERABBIT,
    ]

    # Compiled output directories that APM generates from .apm/ sources.
    # When .apm/ is present these are generated artifacts and should not be linted.
    APM_COMPILED_DIRS = frozenset((".claude", ".cursor", ".gemini", ".opencode", ".agents"))

    def __init__(self, root_path: Path):
        """
        Initialize repository context

        Args:
            root_path: Root directory of the repository
        """
        self.root_path = root_path.resolve()
        self.has_apm = self._detect_apm()
        self.repo_types: Set[RepositoryType] = self._detect_types()
        self.marketplace_data = self._load_marketplace() if self.has_marketplace() else None
        self.plugin_metadata: Dict[Path, Dict[str, Any]] = (
            {}
        )  # marketplace metadata for strict:false plugins without plugin.json
        self.plugins = self._discover_plugins()
        self.skills: List[Path] = self._discover_skills()
        self.instruction_files: List[Path] = self._discover_instruction_files()
        self.detected_formats: Set[str] = self._detect_formats()
        self.content_paths: List[str] = []
        self.exclude_patterns: List[str] = []

    @property
    def repo_type(self) -> RepositoryType:
        """Primary repo type for backward compatibility."""
        for t in self._TYPE_PRIORITY:
            if t in self.repo_types:
                return t
        return RepositoryType.UNKNOWN

    def is_path_excluded(self, path: Path) -> bool:
        """Check if a path matches any exclude pattern."""
        if not self.exclude_patterns:
            return False
        try:
            rel = str(path.resolve().relative_to(self.root_path))
        except ValueError:
            return False
        return any(fnmatch.fnmatch(rel, pat) for pat in self.exclude_patterns)

    def apply_excludes(self) -> None:
        """Filter plugins, skills, and instruction_files by exclude_patterns.

        Must be called after exclude_patterns is set (e.g. from config).
        """
        if not self.exclude_patterns:
            return
        self.plugins = [p for p in self.plugins if not self.is_path_excluded(p)]
        self.skills = [p for p in self.skills if not self.is_path_excluded(p)]
        self.instruction_files = [p for p in self.instruction_files if not self.is_path_excluded(p)]

    def _discover_instruction_files(self) -> List[Path]:
        """Discover instruction files at the repo root and named .instructions.md files.

        Finds:
        - Root-level AGENTS.md, CLAUDE.md, GEMINI.md
        - Any ``*.instructions.md`` files anywhere in the repo tree (Copilot
          named instruction files such as ``coding.instructions.md``)
        """
        files: List[Path] = [
            self.root_path / name
            for name in self._INSTRUCTION_FILENAMES
            if (self.root_path / name).exists()
        ]
        files.extend(self._find_named_instructions_md())
        return files

    def _find_named_instructions_md(self) -> List[Path]:
        """Walk the repo collecting ``*.instructions.md`` files, skipping heavy directories."""
        found: List[Path] = []
        for dirpath, dirnames, filenames in os.walk(self.root_path):
            dirnames[:] = [d for d in dirnames if d not in self._WALK_SKIP_DIRS]
            for f in filenames:
                if f.endswith(".instructions.md"):
                    found.append(Path(dirpath) / f)
        return sorted(found)

    def _detect_formats(self) -> Set[str]:
        formats: Set[str] = set()
        if (self.root_path / ".cursor" / "rules").is_dir() or (
            self.root_path / ".cursorrules"
        ).exists():
            formats.add(HAS_CURSOR)
        if (
            self.root_path / ".github" / "copilot-instructions.md"
        ).exists() or self._has_instructions_md():
            formats.add(HAS_COPILOT)
        if (self.root_path / "GEMINI.md").exists():
            formats.add(HAS_GEMINI)
        if (self.root_path / "AGENTS.md").exists():
            formats.add(HAS_AGENTS_MD)
        if (self.root_path / ".kiro").is_dir():
            formats.add(HAS_KIRO)
        if (self.root_path / "CLAUDE.md").exists():
            formats.add(HAS_CLAUDE_MD)
        if (self.root_path / ".coderabbit.yaml").exists():
            formats.add(HAS_CODERABBIT)
        return formats

    _WALK_SKIP_DIRS = frozenset(
        {
            ".git",
            ".hg",
            ".svn",
            "node_modules",
            ".venv",
            "venv",
            "__pycache__",
            ".tox",
            ".mypy_cache",
        }
    )

    def _has_instructions_md(self) -> bool:
        """Check whether any ``*.instructions.md`` files were discovered."""
        return any(f.name.endswith(".instructions.md") for f in self.instruction_files)

    def _detect_apm(self) -> bool:
        """Check if this repository uses the APM (Agent Package Manager) format"""
        if (self.root_path / ".apm").is_dir():
            return True
        if (self.root_path / "apm.yml").is_file():
            return True
        return False

    def _detect_types(self) -> Set[RepositoryType]:
        """Detect all applicable repository types.

        A repository may match multiple types simultaneously (e.g. a marketplace
        that also has a .coderabbit.yaml).  SINGLE_PLUGIN and MARKETPLACE are
        mutually exclusive (elif chain), but everything else is independent.
        """
        types: Set[RepositoryType] = set()

        # Marketplace / single-plugin (mutually exclusive)
        if (self.root_path / ".claude-plugin" / "marketplace.json").exists():
            types.add(RepositoryType.MARKETPLACE)
        elif (self.root_path / ".claude-plugin").exists():
            types.add(RepositoryType.SINGLE_PLUGIN)
        elif (self.root_path / "plugins").exists():
            types.add(RepositoryType.MARKETPLACE)

        # Agentskills
        if self._is_agentskills_repo():
            types.add(RepositoryType.AGENTSKILLS)

        # CodeRabbit
        if (self.root_path / ".coderabbit.yaml").exists():
            types.add(RepositoryType.CODERABBIT)

        # APM
        if self.has_apm:
            types.add(RepositoryType.APM)

        # DOT_CLAUDE
        if self._is_dot_claude():
            types.add(RepositoryType.DOT_CLAUDE)

        if not types:
            types.add(RepositoryType.UNKNOWN)

        return types

    def _is_agentskills_repo(self) -> bool:
        """Check if this looks like an agentskills.io skill repository"""
        if (self.root_path / "SKILL.md").exists():
            return True

        # Standard discovery paths (checked explicitly since they start with dot)
        for discovery_path in (
            ".apm/skills",
            ".claude/skills",
            ".github/skills",
            ".agents/skills",
        ):
            skills_path = self.root_path / discovery_path
            if skills_path.is_dir() and self._has_skill_md_recursive(skills_path):
                return True

        # Recurse into non-dot subdirectories looking for SKILL.md
        return self._has_skill_md_recursive(self.root_path)

    def _is_dot_claude(self) -> bool:
        """Check if this is a .claude/ directory or a repo containing one.

        When APM is present, .claude/ is a compiled output directory and should
        not drive repo type detection.
        """
        if self.has_apm:
            return False
        claude_dir = self.root_path
        if self.root_path.name != ".claude":
            claude_dir = self.root_path / ".claude"
        if not claude_dir.is_dir():
            return False
        markers = ("commands", "skills", "hooks", "agents", "rules")
        return any((claude_dir / m).is_dir() for m in markers)

    def _has_skill_md_recursive(self, path: Path) -> bool:
        """Check if any subdirectory contains SKILL.md, recursively"""
        try:
            for item in path.iterdir():
                if not item.is_dir() or item.name.startswith("."):
                    continue
                if (item / "SKILL.md").exists():
                    return True
                if self._has_skill_md_recursive(item):
                    return True
        except OSError:
            pass
        return False

    def has_marketplace(self) -> bool:
        """Check if repository has a marketplace"""
        return (self.root_path / ".claude-plugin" / "marketplace.json").exists()

    def _load_marketplace(self) -> Optional[Dict[str, Any]]:
        """Load marketplace.json if it exists"""
        marketplace_file = self.root_path / ".claude-plugin" / "marketplace.json"
        if not marketplace_file.exists():
            return None

        try:
            with open(marketplace_file, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None

    def _resolve_plugin_source(self, source: Any, plugin_entry: Dict[str, Any]) -> Optional[Path]:
        """
        Resolve a plugin source from marketplace.json to a local path

        Handles relative paths (e.g., "./", "./custom/path") and remote sources
        (GitHub repos, git URLs). Remote sources are logged but skipped for local validation.

        Args:
            source: Plugin source (string path or dict with source type)
            plugin_entry: Full plugin entry for context (used for logging)

        Returns:
            Resolved Path if local and valid, None otherwise
        """
        plugin_name = plugin_entry.get("name", "unknown")

        # Handle relative path strings
        if isinstance(source, str):
            candidate = (self.root_path / source).resolve()

            # Disallow escaping the repo with .. paths
            try:
                candidate.relative_to(self.root_path)
            except ValueError:
                logger.warning(
                    "Plugin '%s' source '%s' escapes repository root. Skipping.",
                    plugin_name,
                    source,
                )
                return None

            if not candidate.exists():
                logger.info(
                    "Plugin '%s' source '%s' not found locally. Skipping.", plugin_name, source
                )
                return None

            if not candidate.is_dir():
                logger.info(
                    "Plugin '%s' source '%s' is not a directory. Skipping.", plugin_name, source
                )
                return None

            return candidate

        # Handle remote source objects (GitHub, git URLs)
        if isinstance(source, dict):
            source_type = source.get("source", "unknown")
            source_info = source.get("repo") or source.get("url", "unknown")
            logger.info(
                "Plugin '%s' uses remote source (%s: %s). Skipping local validation.",
                plugin_name,
                source_type,
                source_info,
            )
            return None

        # Unknown format
        logger.info("Plugin '%s' has unknown source format. Skipping.", plugin_name)
        return None

    def _is_valid_plugin_dir(
        self, path: Path, marketplace_entry: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Check if a directory is a valid plugin directory

        A directory is valid if it has plugin.json, standard component directories
        (commands, agents, skills, hooks), or if the marketplace entry has strict: false.

        Args:
            path: Directory path to check
            marketplace_entry: Optional marketplace entry for the plugin

        Returns:
            True if directory appears to be a valid plugin
        """
        # Check for plugin.json or standard component directories
        plugin_markers = [
            path / ".claude-plugin" / "plugin.json",
            path / "commands",
            path / "agents",
            path / "skills",
            path / "hooks",
        ]

        if any(marker.exists() for marker in plugin_markers):
            return True

        # When strict:false, plugin.json and component dirs can be absent
        if marketplace_entry is not None and marketplace_entry.get("strict", True) is False:
            return True

        return False

    def _discover_plugins(self) -> List[Path]:
        """
        Discover all plugin directories in the repository

        Handles three discovery methods:
        1. Single plugin at repository root
        2. Traditional plugins/ directory (backward compatibility)
        3. Marketplace.json-defined sources (flat structures, custom paths, remote)

        Multiple types can contribute plugins simultaneously.
        """
        plugins: List[Path] = []
        discovered_paths: Set[Path] = set()

        if RepositoryType.SINGLE_PLUGIN in self.repo_types:
            plugins.append(self.root_path)
            discovered_paths.add(self.root_path.resolve())

        if (
            RepositoryType.DOT_CLAUDE in self.repo_types
            and RepositoryType.MARKETPLACE not in self.repo_types
        ):
            claude_dir = (
                self.root_path if self.root_path.name == ".claude" else self.root_path / ".claude"
            )
            if claude_dir.resolve() not in discovered_paths:
                plugins.append(claude_dir)
                discovered_paths.add(claude_dir.resolve())

        if RepositoryType.MARKETPLACE in self.repo_types:
            # Discover from plugins/ directory (backward compatibility)
            self._discover_from_plugins_dir(plugins, discovered_paths)

            # Discover from marketplace.json plugin entries
            self._discover_from_marketplace(plugins, discovered_paths)

        return plugins

    def _discover_from_plugins_dir(self, plugins: List[Path], discovered_paths: Set[Path]) -> None:
        """Discover plugins from traditional plugins/ directory"""
        plugins_dir = self.root_path / "plugins"
        if not plugins_dir.exists():
            return

        for item in plugins_dir.iterdir():
            if not item.is_dir() or item.name.startswith("."):
                continue

            # Must have .claude-plugin or commands directory
            if not ((item / ".claude-plugin").exists() or (item / "commands").exists()):
                continue

            resolved_path = item.resolve()
            if resolved_path not in discovered_paths:
                plugins.append(item)
                discovered_paths.add(resolved_path)

    def _discover_from_marketplace(self, plugins: List[Path], discovered_paths: Set[Path]) -> None:
        """Discover plugins from marketplace.json plugin entries"""
        if not self.marketplace_data or "plugins" not in self.marketplace_data:
            return

        for plugin_entry in self.marketplace_data["plugins"]:
            if not isinstance(plugin_entry, dict):
                continue
            source = plugin_entry.get("source")
            if not source:
                continue

            # Resolve source to local path (or skip if remote)
            plugin_path = self._resolve_plugin_source(source, plugin_entry)
            if not plugin_path:
                continue

            # Skip duplicates
            resolved_path = plugin_path.resolve()
            if resolved_path in discovered_paths:
                continue

            # Validate plugin directory
            if not self._is_valid_plugin_dir(plugin_path, plugin_entry):
                continue

            plugins.append(plugin_path)
            discovered_paths.add(resolved_path)

            # Store metadata for strict: false plugins without plugin.json
            is_strict = plugin_entry.get("strict", True)
            has_plugin_json = (plugin_path / ".claude-plugin" / "plugin.json").exists()

            if not is_strict and not has_plugin_json:
                self.plugin_metadata[resolved_path] = plugin_entry

    def get_plugin_name(self, plugin_path: Path) -> str:
        """
        Get the name of a plugin from its path

        Checks plugin.json first, falls back to marketplace metadata,
        then directory name.
        """
        resolved_path = plugin_path.resolve()

        # Try plugin.json
        plugin_json = plugin_path / ".claude-plugin" / "plugin.json"
        if plugin_json.exists():
            try:
                with open(plugin_json, "r") as f:
                    data = json.load(f)
                    if name := data.get("name"):
                        return name
            except (json.JSONDecodeError, IOError):
                pass

        # Try marketplace metadata
        if resolved_path in self.plugin_metadata:
            return self.plugin_metadata[resolved_path].get("name", plugin_path.name)

        # Fall back to directory name
        return plugin_path.name

    def is_registered_in_marketplace(self, plugin_name: str) -> bool:
        """Check if a plugin is registered in marketplace.json"""
        if not self.marketplace_data or "plugins" not in self.marketplace_data:
            return False

        return any(p.get("name") == plugin_name for p in self.marketplace_data["plugins"])

    def get_plugin_metadata(self, plugin_path: Path) -> Optional[Dict[str, Any]]:
        """
        Get complete metadata for a plugin

        Returns metadata from plugin.json if present, otherwise falls back to
        marketplace entry data (for strict: false plugins without plugin.json).

        Args:
            plugin_path: Path to the plugin directory

        Returns:
            Dictionary with plugin metadata, or None if no metadata found
        """
        metadata = {}
        resolved_path = plugin_path.resolve()

        # Load from plugin.json if present
        plugin_json = plugin_path / ".claude-plugin" / "plugin.json"
        if plugin_json.exists():
            try:
                with open(plugin_json, "r") as f:
                    metadata = json.load(f)
            except (json.JSONDecodeError, IOError):
                pass

        # Use marketplace metadata as fallback (for strict: false without plugin.json)
        if resolved_path in self.plugin_metadata:
            marketplace_entry = self.plugin_metadata[resolved_path]

            # Exclude marketplace-specific fields
            for key, value in marketplace_entry.items():
                if key not in ("source", "strict"):
                    metadata[key] = value

        return metadata or None

    def _discover_skills(self) -> List[Path]:
        """
        Discover agentskills.io skill directories.

        For AGENTSKILLS repos: root (single skill) or subdirs with SKILL.md.
        For plugin repos: skills from plugin_path/skills/*/.

        When APM is present, skills are discovered from .apm/skills/ and
        compiled output directories are excluded.
        """
        skills: List[Path] = []
        discovered: Set[Path] = set()

        # Build set of compiled output directories to skip when APM is present
        apm_excluded_roots: Set[Path] = set()
        if self.has_apm:
            for compiled_dir_name in self.APM_COMPILED_DIRS:
                compiled_path = (self.root_path / compiled_dir_name).resolve()
                if compiled_path.is_dir():
                    apm_excluded_roots.add(compiled_path)

        if RepositoryType.AGENTSKILLS in self.repo_types:
            # Single skill at root
            if (self.root_path / "SKILL.md").exists():
                skills.append(self.root_path)
                discovered.add(self.root_path)
            else:
                # Skill collection: immediate subdirs with SKILL.md
                self._discover_skills_in_dir(self.root_path, skills, discovered)

            # Standard discovery paths (including APM)
            for discovery_path in (
                ".apm/skills",
                ".claude/skills",
                ".github/skills",
                ".agents/skills",
            ):
                skills_path = self.root_path / discovery_path
                if not skills_path.is_dir():
                    continue
                # Skip compiled output dirs when APM is present
                if any(
                    skills_path.resolve() == excl or skills_path.resolve().is_relative_to(excl)
                    for excl in apm_excluded_roots
                ):
                    continue
                self._discover_skills_in_dir(skills_path, skills, discovered)

        # For plugin repos, also discover embedded skills
        for plugin_path in self.plugins:
            skills_dir = plugin_path / "skills"
            if skills_dir.is_dir():
                self._discover_skills_in_dir(skills_dir, skills, discovered)

        return skills

    def _discover_skills_in_dir(
        self, parent: Path, skills: List[Path], discovered: Set[Path]
    ) -> None:
        """Discover skill directories within a parent directory, recursively"""
        try:
            for item in parent.iterdir():
                if not item.is_dir() or item.name.startswith("."):
                    continue
                resolved = item.resolve()
                if resolved in discovered:
                    continue
                if (item / "SKILL.md").exists():
                    skills.append(item)
                    discovered.add(resolved)
                else:
                    self._discover_skills_in_dir(item, skills, discovered)
        except OSError:
            pass

    def __str__(self):
        """String representation of context"""
        return f"RepositoryContext(type={self.repo_type.value}, plugins={len(self.plugins)}, skills={len(self.skills)})"

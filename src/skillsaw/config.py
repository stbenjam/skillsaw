"""
Configuration management for skillsaw
"""

import os

import yaml
from pathlib import Path
from typing import Dict, Any, Optional, List, Set, Tuple, TYPE_CHECKING
from dataclasses import dataclass, field

if TYPE_CHECKING:
    from .context import RepositoryContext

_DEFAULT_VERSION = "0.6.0"


def _parse_version(v: str) -> Tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


@dataclass
class LLMSettings:
    model: str = ""
    max_iterations: int = 10
    max_tokens: int = 500_000
    confirm: bool = True
    max_workers: int = 4

    def __post_init__(self):
        env_model = os.environ.get("SKILLSAW_MODEL")
        if env_model:
            self.model = env_model


@dataclass
class LinterConfig:
    """Configuration for the linter"""

    version: str = ""
    rules: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    custom_rules: List[str] = field(default_factory=list)
    exclude_patterns: List[str] = field(default_factory=list)
    content_paths: List[str] = field(default_factory=list)
    strict: bool = False
    llm: LLMSettings = field(default_factory=LLMSettings)

    @classmethod
    def from_file(cls, config_path: Path) -> "LinterConfig":
        """
        Load configuration from a config file

        Args:
            config_path: Path to configuration file

        Returns:
            LinterConfig instance
        """
        if not config_path.exists():
            return cls()

        try:
            with open(config_path, "r") as f:
                data = yaml.safe_load(f) or {}
        except (yaml.YAMLError, IOError) as e:
            raise ValueError(f"Failed to load config from {config_path}: {e}")

        raw_rules = data.get("rules")
        raw_custom_rules = data.get("custom-rules")
        raw_exclude = data.get("exclude")
        raw_strict = data.get("strict")

        if raw_rules is None:
            rules = {}
        elif isinstance(raw_rules, dict):
            rules = raw_rules
        else:
            raise ValueError(
                f"'rules' must be a mapping, got {type(raw_rules).__name__}. "
                "Each rule should be a key with a mapping value, e.g.:\n"
                "  rules:\n"
                "    plugin-json-required:\n"
                "      enabled: true"
            )

        for rule_id, rule_config in rules.items():
            if rule_config is None:
                rules[rule_id] = {}
            elif not isinstance(rule_config, dict):
                raise ValueError(
                    f"'rules.{rule_id}' must be a mapping or null, "
                    f"got {type(rule_config).__name__}"
                )

        if raw_custom_rules is None:
            custom_rules = []
        elif isinstance(raw_custom_rules, list):
            custom_rules = raw_custom_rules
        else:
            raise ValueError(
                f"'custom-rules' must be a list, got {type(raw_custom_rules).__name__}"
            )

        if raw_exclude is None:
            exclude_patterns = []
        elif isinstance(raw_exclude, list):
            exclude_patterns = raw_exclude
        else:
            raise ValueError(f"'exclude' must be a list, got {type(raw_exclude).__name__}")

        if raw_strict is None:
            strict = False
        elif isinstance(raw_strict, bool):
            strict = raw_strict
        else:
            raise ValueError(f"'strict' must be a boolean, got {type(raw_strict).__name__}")

        llm_data = data.get("llm", {})
        llm_settings = LLMSettings(
            model=llm_data.get("model", LLMSettings.model),
            max_iterations=llm_data.get("max_iterations", LLMSettings.max_iterations),
            max_tokens=llm_data.get("max_tokens", LLMSettings.max_tokens),
            confirm=llm_data.get("confirm", LLMSettings.confirm),
            max_workers=llm_data.get("max_workers", LLMSettings.max_workers),
        )

        return cls(
            version=data.get("version", _DEFAULT_VERSION),
            rules=rules,
            custom_rules=custom_rules,
            exclude_patterns=exclude_patterns,
            content_paths=data.get("content-paths", []),
            strict=strict,
            llm=llm_settings,
        )

    @classmethod
    def default(cls) -> "LinterConfig":
        """Create default configuration with all builtin rules enabled"""
        from . import __version__

        return cls(
            version=__version__,
            rules={
                # Plugin structure rules (auto-enabled for plugin/marketplace repos)
                "plugin-json-required": {"enabled": "auto", "severity": "error"},
                "plugin-json-valid": {
                    "enabled": "auto",
                    "severity": "error",
                    "recommended-fields": ["description", "version", "author"],
                },
                "plugin-naming": {"enabled": "auto", "severity": "warning"},
                # Command format rules
                "command-naming": {"enabled": True, "severity": "warning"},
                "command-frontmatter": {"enabled": True, "severity": "error"},
                "command-sections": {"enabled": False, "severity": "warning"},
                "command-name-format": {"enabled": False, "severity": "warning"},
                # Marketplace rules (auto-enabled for marketplace repos)
                "marketplace-json-valid": {"enabled": "auto", "severity": "error"},
                "marketplace-registration": {"enabled": "auto", "severity": "error"},
                # Documentation rules
                "plugin-readme": {"enabled": "auto", "severity": "warning"},
                # Skills rules
                "skill-frontmatter": {"enabled": True, "severity": "warning"},
                # Agents rules
                "agent-frontmatter": {"enabled": True, "severity": "error"},
                # Hooks rules
                "hooks-json-valid": {"enabled": True, "severity": "error"},
                # MCP rules
                "mcp-valid-json": {"enabled": True, "severity": "error"},
                "mcp-prohibited": {"enabled": False, "severity": "error"},
                # Rules directory
                "rules-valid": {"enabled": "auto", "severity": "error"},
                # Agentskills rules (auto-enabled for agentskills repos)
                "agentskill-valid": {"enabled": "auto", "severity": "error"},
                "agentskill-name": {"enabled": "auto", "severity": "error"},
                "agentskill-description": {"enabled": "auto", "severity": "warning"},
                "agentskill-structure": {"enabled": False, "severity": "warning"},
                "agentskill-evals-required": {"enabled": False, "severity": "warning"},
                "agentskill-evals": {"enabled": "auto", "severity": "warning"},
                # Openclaw metadata
                "openclaw-metadata": {"enabled": "auto", "severity": "warning"},
                # Instruction file validation (auto-enabled when instruction files detected)
                "instruction-file-valid": {"enabled": "auto", "severity": "warning"},
                "instruction-imports-valid": {"enabled": "auto", "severity": "warning"},
                # Context budget (opt-in; checks token limits across skills/commands/files)
                "context-budget": {"enabled": "auto", "severity": "warning"},
                # Content intelligence rules (auto-enabled when instruction files detected)
                "content-weak-language": {"enabled": "auto", "severity": "warning"},
                "content-tautological": {"enabled": "auto", "severity": "warning"},
                "content-critical-position": {
                    "enabled": "auto",
                    "severity": "warning",
                    "min-lines": 50,
                },
                "content-redundant-with-tooling": {"enabled": "auto", "severity": "warning"},
                "content-instruction-budget": {"enabled": "auto", "severity": "warning"},
                "content-negative-only": {"enabled": "auto", "severity": "warning"},
                "content-section-length": {"enabled": "auto", "severity": "info"},
                "content-contradiction": {"enabled": "auto", "severity": "warning"},
                "content-hook-candidate": {"enabled": "auto", "severity": "info"},
                "content-actionability-score": {"enabled": "auto", "severity": "info"},
                "content-cognitive-chunks": {"enabled": "auto", "severity": "info"},
                "content-embedded-secrets": {"enabled": "auto", "severity": "error"},
                "content-banned-references": {"enabled": "auto", "severity": "warning"},
                "content-inconsistent-terminology": {"enabled": "auto", "severity": "info"},
                # CodeRabbit config
                "coderabbit-yaml-valid": {"enabled": "auto", "severity": "error"},
                # APM (Agent Package Manager) rules
                "apm-yaml-valid": {"enabled": "auto", "severity": "error"},
                "apm-structure-valid": {"enabled": "auto", "severity": "warning"},
            },
        )

    @classmethod
    def for_init(cls) -> "LinterConfig":
        """Config for --init: sets version to current release so all rules are active."""
        from . import __version__

        config = cls.default()
        config.version = __version__
        return config

    def get_rule_config(self, rule_id: str) -> Dict[str, Any]:
        """
        Get configuration for a specific rule, merging user overrides
        on top of defaults so unmentioned fields keep their default values.

        Args:
            rule_id: Rule identifier

        Returns:
            Rule configuration dict
        """
        defaults = self.default().rules.get(rule_id, {})
        overrides = self.rules.get(rule_id)
        if overrides is None:
            overrides = {}
        merged = {**defaults, **overrides}
        return merged

    def is_rule_enabled(
        self,
        rule_id: str,
        context: "RepositoryContext",
        repo_types=None,
        formats: Optional[Set[str]] = None,
        since_version: str = "0.1.0",
    ) -> bool:
        """
        Check if a rule is enabled for the given context

        Args:
            rule_id: Rule identifier
            context: Repository context
            repo_types: Set of RepositoryType values the rule applies to (None = all)
            formats: Set of detected format constants the rule requires (None = all)
            since_version: Minimum config version required for this rule

        Returns:
            True if rule should run
        """
        user_overrides = self.rules.get(rule_id, {})
        has_explicit_enabled = "enabled" in user_overrides
        if has_explicit_enabled:
            explicit = user_overrides["enabled"]
            if explicit is True:
                return True
            if explicit is False:
                return False
            # enabled: "auto" falls through to version gate + auto logic below
        else:
            # Any non-enabled override (e.g. severity) without an explicit
            # ``enabled`` key on a disabled-by-default rule implies the user
            # wants it active.  We must NOT do this for ``enabled: "auto"``
            # rules — those rely on repo-type / format detection.
            if user_overrides:
                default_enabled = self.default().rules.get(rule_id, {}).get("enabled", True)
                if default_enabled is False:
                    return True
                # For "auto" rules, non-enabled overrides don't change
                # activation — fall through to version gate + auto logic.

        # Any explicit user override (enabled or otherwise) implies the user
        # wants this rule, so skip the version gate.
        has_user_overrides = bool(user_overrides)

        if not has_user_overrides and self.version:
            if _parse_version(self.version) < _parse_version(since_version):
                return False

        rule_config = self.get_rule_config(rule_id)
        enabled = rule_config.get("enabled", True)

        if enabled == "auto":
            if repo_types is None and formats is None:
                return True
            if repo_types is not None and repo_types & context.repo_types:
                return True
            if formats is not None and formats & context.detected_formats:
                return True
            return False

        return bool(enabled)

    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary for serialization"""
        d: Dict[str, Any] = {}
        if self.version:
            d["version"] = self.version
        d["rules"] = self.rules
        d["custom-rules"] = self.custom_rules
        d["exclude"] = self.exclude_patterns
        d["strict"] = self.strict
        if self.content_paths:
            d["content-paths"] = self.content_paths
        return d

    def save(self, config_path: Path):
        """Save configuration to file with rule descriptions as comments"""
        from .rules.builtin import BUILTIN_RULES

        descriptions = {}
        for rule_class in BUILTIN_RULES:
            rule = rule_class()
            descriptions[rule.rule_id] = rule.description

        with open(config_path, "w") as f:
            f.write("# skillsaw configuration\n")
            f.write("# https://github.com/stbenjam/skillsaw\n\n")
            if self.version:
                f.write(f'version: "{self.version}"\n\n')
            f.write("rules:\n")
            for rule_id, rule_config in self.rules.items():
                desc = descriptions.get(rule_id, "")
                if desc:
                    f.write(f"\n  # {desc}\n")
                f.write(f"  {rule_id}:\n")
                for key, value in rule_config.items():
                    yaml_val = self._yaml_value(value)
                    if yaml_val.startswith("\n"):
                        f.write(f"    {key}:{yaml_val}\n")
                    else:
                        f.write(f"    {key}: {yaml_val}\n")

            f.write("\n# Load custom rules from these files\n")
            f.write(f"custom-rules: {self._yaml_value(self.custom_rules)}\n")
            f.write("\n# Exclude patterns (glob format)\n")
            f.write(f"exclude: {self._yaml_value(self.exclude_patterns)}\n")
            f.write("\n# Additional markdown files to run content rules on (glob format)\n")
            f.write(f"content-paths: {self._yaml_value(self.content_paths)}\n")
            f.write("\n# Treat warnings as errors\n")
            f.write(f"strict: {self._yaml_value(self.strict)}\n")

    @staticmethod
    def _yaml_value(value, indent=4):
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, list):
            if not value:
                return "[]"
            pad = " " * indent
            return "\n" + "\n".join(f"{pad}- {item}" for item in value)
        if isinstance(value, dict):
            if not value:
                return "{}"
            pad = " " * indent
            lines = []
            for k, v in value.items():
                rendered = LinterConfig._yaml_value(v, indent + 2)
                if rendered.startswith("\n"):
                    lines.append(f"{pad}{k}:{rendered}")
                else:
                    lines.append(f"{pad}{k}: {rendered}")
            return "\n" + "\n".join(lines)
        if isinstance(value, str):
            return value
        return str(value)


def find_config(start_path: Path) -> Optional[Path]:
    """
    Find config file by walking up the directory tree.

    Checks for .skillsaw.yaml first, then falls back to .claudelint.yaml
    for backward compatibility.
    """
    current = start_path.resolve()

    while current != current.parent:
        for name in (
            ".skillsaw.yaml",
            ".skillsaw.yml",
            ".claudelint.yaml",
            ".claudelint.yml",
        ):
            config_file = current / name
            if config_file.exists():
                return config_file

        current = current.parent

    return None

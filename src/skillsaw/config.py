"""
Configuration management for skillsaw
"""

import yaml
from pathlib import Path
from typing import Dict, Any, Optional, List, TYPE_CHECKING
from dataclasses import dataclass, field

if TYPE_CHECKING:
    from .context import RepositoryContext


@dataclass
class LinterConfig:
    """Configuration for the linter"""

    rules: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    custom_rules: List[str] = field(default_factory=list)
    exclude_patterns: List[str] = field(default_factory=list)
    strict: bool = False

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

        return cls(
            rules=data.get("rules", {}),
            custom_rules=data.get("custom-rules", []),
            exclude_patterns=data.get("exclude", []),
            strict=data.get("strict", False),
        )

    @classmethod
    def default(cls) -> "LinterConfig":
        """Create default configuration with all builtin rules enabled"""
        return cls(
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
                "command-sections": {"enabled": True, "severity": "warning"},
                "command-name-format": {"enabled": True, "severity": "warning"},
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
                # Agentskills rules (auto-enabled for agentskills repos)
                "agentskill-valid": {"enabled": "auto", "severity": "error"},
                "agentskill-name": {"enabled": "auto", "severity": "error"},
                "agentskill-description": {"enabled": "auto", "severity": "warning"},
                "agentskill-structure": {"enabled": "auto", "severity": "warning"},
                "agentskill-evals-required": {"enabled": False, "severity": "warning"},
                "agentskill-evals": {"enabled": "auto", "severity": "warning"},
            }
        )

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
        overrides = self.rules.get(rule_id, {})
        merged = {**defaults, **overrides}
        return merged

    def is_rule_enabled(self, rule_id: str, context: "RepositoryContext", repo_types=None) -> bool:
        """
        Check if a rule is enabled for the given context

        Args:
            rule_id: Rule identifier
            context: Repository context
            repo_types: Set of RepositoryType values the rule applies to (None = all)

        Returns:
            True if rule should run
        """
        rule_config = self.get_rule_config(rule_id)
        enabled = rule_config.get("enabled", True)

        if enabled == "auto":
            if repo_types is None:
                return True
            return context.repo_type in repo_types

        return bool(enabled)

    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary for serialization"""
        return {
            "rules": self.rules,
            "custom-rules": self.custom_rules,
            "exclude": self.exclude_patterns,
            "strict": self.strict,
        }

    def save(self, config_path: Path):
        """Save configuration to file"""
        with open(config_path, "w") as f:
            yaml.dump(self.to_dict(), f, default_flow_style=False, sort_keys=False)


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

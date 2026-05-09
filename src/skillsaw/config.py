"""
Configuration management for skillsaw
"""

import os

import yaml
from pathlib import Path
from typing import Dict, Any, Optional, List, Set, TYPE_CHECKING
from dataclasses import dataclass, field

if TYPE_CHECKING:
    from .context import RepositoryContext


@dataclass
class LLMSettings:
    model: str = "claude-sonnet-4-20250514"
    max_iterations: int = 3
    max_tokens: int = 500_000
    confirm: bool = True

    def __post_init__(self):
        env_model = os.environ.get("SKILLSAW_MODEL")
        if env_model:
            self.model = env_model


@dataclass
class LinterConfig:
    """Configuration for the linter"""

    rules: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    custom_rules: List[str] = field(default_factory=list)
    exclude_patterns: List[str] = field(default_factory=list)
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

        llm_data = data.get("llm", {})
        llm_settings = LLMSettings(
            model=llm_data.get("model", LLMSettings.model),
            max_iterations=llm_data.get("max_iterations", LLMSettings.max_iterations),
            max_tokens=llm_data.get("max_tokens", LLMSettings.max_tokens),
            confirm=llm_data.get("confirm", LLMSettings.confirm),
        )

        return cls(
            rules=data.get("rules", {}),
            custom_rules=data.get("custom-rules", []),
            exclude_patterns=data.get("exclude", []),
            strict=data.get("strict", False),
            llm=llm_settings,
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
                # Copilot instructions (auto-enabled when copilot files detected)
                "copilot-instructions-valid": {"enabled": "auto", "severity": "warning"},
                "copilot-dot-instructions-valid": {"enabled": "auto", "severity": "warning"},
                # Copilot deep rules (auto-enabled when copilot files detected)
                "copilot-instructions-length": {"enabled": "auto", "severity": "warning"},
                "copilot-instructions-language-quality": {"enabled": "auto", "severity": "info"},
                "copilot-instructions-actionability": {"enabled": "auto", "severity": "warning"},
                "copilot-instructions-stale-refs": {"enabled": "auto", "severity": "warning"},
                "copilot-instructions-duplication": {"enabled": "auto", "severity": "warning"},
                "copilot-instructions-scope": {"enabled": "auto", "severity": "warning"},
                "copilot-instructions-format": {"enabled": "auto", "severity": "warning"},
                "copilot-instructions-conflict": {"enabled": "auto", "severity": "warning"},
                "copilot-instructions-frontmatter-keys": {"enabled": "auto", "severity": "warning"},
                "copilot-instructions-exclude-agent": {"enabled": "auto", "severity": "error"},
                "agents-md-structure": {"enabled": "auto", "severity": "warning"},
                # Deep AGENTS.md rules (disabled for back-compat; --init enables)
                "agents-md-size-limit": {"enabled": "auto", "severity": "warning"},
                "agents-md-override-semantics": {"enabled": "auto", "severity": "warning"},
                "agents-md-hierarchy-consistency": {"enabled": "auto", "severity": "warning"},
                "agents-md-dead-file-refs": {"enabled": "auto", "severity": "warning"},
                "agents-md-dead-command-refs": {"enabled": "auto", "severity": "warning"},
                "agents-md-weak-language": {"enabled": "auto", "severity": "info"},
                "agents-md-negative-only": {"enabled": "auto", "severity": "warning"},
                "agents-md-section-length": {"enabled": "auto", "severity": "warning"},
                "agents-md-structure-deep": {"enabled": "auto", "severity": "info"},
                "agents-md-tautological": {"enabled": "auto", "severity": "warning"},
                "agents-md-critical-position": {"enabled": "auto", "severity": "info"},
                "agents-md-hook-candidate": {"enabled": "auto", "severity": "info"},
                # Context budget (opt-in; checks token limits across skills/commands/files)
                "context-budget": {"enabled": False, "severity": "warning"},
                # Cursor rules (auto-enabled when .cursor/ or .cursorrules detected)
                "cursor-mdc-valid": {"enabled": "auto", "severity": "error"},
                "cursor-rules-deprecated": {"enabled": "auto", "severity": "warning"},
                # Kiro steering (auto-enabled when .kiro/ detected)
                "kiro-steering-valid": {"enabled": "auto", "severity": "error"},
                # Cursor deep rules (auto-enabled when .cursor/ present)
                "cursor-mdc-frontmatter": {"enabled": "auto", "severity": "warning"},
                "cursor-activation-type": {"enabled": "auto", "severity": "warning"},
                "cursor-crlf-detection": {"enabled": "auto", "severity": "error"},
                "cursor-glob-valid": {"enabled": "auto", "severity": "warning"},
                "cursor-empty-body": {"enabled": "auto", "severity": "warning"},
                "cursor-description-quality": {"enabled": "auto", "severity": "warning"},
                "cursor-glob-overlap": {"enabled": "auto", "severity": "warning"},
                "cursor-rule-size": {"enabled": "auto", "severity": "warning"},
                "cursor-frontmatter-types": {"enabled": "auto", "severity": "error"},
                "cursor-duplicate-rules": {"enabled": "auto", "severity": "warning"},
                "cursor-always-apply-overuse": {"enabled": "auto", "severity": "warning"},
                # Gemini rules (auto-enabled when GEMINI.md detected)
                "gemini-import-valid": {"enabled": "auto", "severity": "warning"},
                "gemini-import-circular": {"enabled": "auto", "severity": "error"},
                "gemini-import-depth": {"enabled": "auto", "severity": "warning"},
                "gemini-scope-false-positive": {"enabled": "auto", "severity": "warning"},
                "gemini-hierarchy-consistency": {"enabled": "auto", "severity": "warning"},
                "gemini-size-limit": {"enabled": "auto", "severity": "warning"},
                "gemini-dead-file-refs": {"enabled": "auto", "severity": "warning"},
                "gemini-weak-language": {"enabled": "auto", "severity": "info"},
                "gemini-tautological": {"enabled": "auto", "severity": "info"},
                "gemini-critical-position": {"enabled": "auto", "severity": "info"},
                # APM manifest rules (auto-enabled for APM repos)
                "apm-manifest-valid": {"enabled": "auto", "severity": "error"},
                "apm-target-valid": {"enabled": "auto", "severity": "error"},
                "apm-type-valid": {"enabled": "auto", "severity": "error"},
                "apm-dependencies-valid": {"enabled": "auto", "severity": "error"},
                "apm-compilation-valid": {"enabled": "auto", "severity": "warning"},
                # Content intelligence rules (auto-enabled when instruction files detected)
                "content-weak-language": {"enabled": "auto", "severity": "warning"},
                "content-dead-references": {"enabled": "auto", "severity": "warning"},
                "content-tautological": {"enabled": "auto", "severity": "warning"},
                "content-critical-position": {"enabled": "auto", "severity": "info"},
                "content-redundant-with-tooling": {"enabled": "auto", "severity": "warning"},
                "content-instruction-budget": {"enabled": "auto", "severity": "warning"},
                "content-readme-overlap": {"enabled": "auto", "severity": "info"},
                "content-negative-only": {"enabled": "auto", "severity": "warning"},
                "content-section-length": {"enabled": "auto", "severity": "info"},
                "content-contradiction": {"enabled": "auto", "severity": "warning"},
                "content-hook-candidate": {"enabled": "auto", "severity": "info"},
                "content-actionability-score": {"enabled": "auto", "severity": "info"},
                "content-cognitive-chunks": {"enabled": "auto", "severity": "info"},
                "content-embedded-secrets": {"enabled": "auto", "severity": "error"},
                "content-cross-file-consistency": {"enabled": "auto", "severity": "warning"},
                "apm-mcp-transport": {"enabled": "auto", "severity": "error"},
                "apm-lockfile-consistency": {"enabled": "auto", "severity": "warning"},
                "apm-readme-present": {"enabled": "auto", "severity": "warning"},
                "apm-entry-point": {"enabled": "auto", "severity": "error"},
                "apm-name-conflict": {"enabled": "auto", "severity": "warning"},
                "apm-field-types": {"enabled": "auto", "severity": "error"},
                "apm-deprecated-fields": {"enabled": "auto", "severity": "warning"},
            }
        )

    @classmethod
    def for_init(cls) -> "LinterConfig":
        """Config for --init: identical to default() now that all rules use auto-detection."""
        return cls.default()

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

    def is_rule_enabled(
        self,
        rule_id: str,
        context: "RepositoryContext",
        repo_types=None,
        formats: Optional[Set[str]] = None,
    ) -> bool:
        """
        Check if a rule is enabled for the given context

        Args:
            rule_id: Rule identifier
            context: Repository context
            repo_types: Set of RepositoryType values the rule applies to (None = all)
            formats: Set of detected format constants the rule requires (None = all)

        Returns:
            True if rule should run
        """
        rule_config = self.get_rule_config(rule_id)
        enabled = rule_config.get("enabled", True)

        if enabled == "auto":
            if repo_types is None and formats is None:
                return True
            if repo_types is not None and context.repo_type in repo_types:
                return True
            if formats is not None and formats & context.detected_formats:
                return True
            return False

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
        """Save configuration to file with rule descriptions as comments"""
        from .rules.builtin import BUILTIN_RULES

        descriptions = {}
        for rule_class in BUILTIN_RULES:
            rule = rule_class()
            descriptions[rule.rule_id] = rule.description

        with open(config_path, "w") as f:
            f.write("# skillsaw configuration\n")
            f.write("# https://github.com/stbenjam/skillsaw\n\n")
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

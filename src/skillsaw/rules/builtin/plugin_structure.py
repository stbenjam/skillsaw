"""
Rules for validating plugin structure
"""

import re
from pathlib import Path
from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.rules.builtin.utils import read_json
from skillsaw.context import RepositoryContext, RepositoryType

PLUGIN_REPO_TYPES = {RepositoryType.SINGLE_PLUGIN, RepositoryType.MARKETPLACE}


class PluginJsonRequiredRule(Rule):
    """Check that plugin.json exists"""

    repo_types = PLUGIN_REPO_TYPES

    @property
    def rule_id(self) -> str:
        return "plugin-json-required"

    @property
    def description(self) -> str:
        return "Plugin must have .claude-plugin/plugin.json"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        for plugin_path in context.plugins:
            plugin_json = plugin_path / ".claude-plugin" / "plugin.json"
            if not plugin_json.exists():
                # Check if plugin has strict: false in marketplace metadata
                resolved_path = plugin_path.resolve()
                if resolved_path in getattr(context, "plugin_metadata", {}):
                    marketplace_entry = context.plugin_metadata[resolved_path]
                    if marketplace_entry.get("strict", True) is False:
                        # When strict: false, plugin.json is optional
                        continue

                violations.append(self.violation("Missing plugin.json", file_path=plugin_json))

        return violations


class PluginJsonValidRule(Rule):
    """Check that plugin.json is valid and has required fields"""

    repo_types = PLUGIN_REPO_TYPES

    DEFAULT_RECOMMENDED_FIELDS = ["description", "version", "author"]
    config_schema = {
        "recommended-fields": {
            "type": "list",
            "default": DEFAULT_RECOMMENDED_FIELDS,
            "description": "Fields that trigger a warning if missing from plugin.json",
        },
    }

    @property
    def rule_id(self) -> str:
        return "plugin-json-valid"

    @property
    def description(self) -> str:
        return "Plugin.json must be valid JSON with required fields"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        recommended_fields = self.config.get("recommended-fields", self.DEFAULT_RECOMMENDED_FIELDS)

        for plugin_path in context.plugins:
            plugin_json = plugin_path / ".claude-plugin" / "plugin.json"

            if not plugin_json.exists():
                continue  # Handled by plugin-json-required rule

            # Try to parse JSON
            data, error = read_json(plugin_json)
            if error:
                violations.append(self.violation(f"Invalid JSON: {error}", file_path=plugin_json))
                continue

            # Check required fields
            required_fields = ["name"]
            for field in required_fields:
                if field not in data:
                    violations.append(
                        self.violation(f"Missing required field '{field}'", file_path=plugin_json)
                    )

            # Check recommended fields (warning)
            for field in recommended_fields:
                if field not in data:
                    violations.append(
                        self.violation(
                            f"Missing recommended field '{field}'",
                            file_path=plugin_json,
                            severity=Severity.WARNING,
                        )
                    )

            # Validate version format (semver)
            if "version" in data:
                version = data["version"]
                if not re.match(
                    r"^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?(\+[a-zA-Z0-9.]+)?$", str(version)
                ):
                    violations.append(
                        self.violation(
                            f"Version '{version}' should follow semver (X.Y.Z)",
                            file_path=plugin_json,
                        )
                    )

            # Validate author structure
            if "author" in data:
                author = data["author"]
                if not isinstance(author, dict) or "name" not in author:
                    violations.append(
                        self.violation(
                            "Author must be an object with 'name' field",
                            file_path=plugin_json,
                        )
                    )

        return violations


class PluginNamingRule(Rule):
    """Check that plugin follows naming conventions"""

    repo_types = PLUGIN_REPO_TYPES

    @property
    def rule_id(self) -> str:
        return "plugin-naming"

    @property
    def description(self) -> str:
        return "Plugin names should use kebab-case"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        for plugin_path in context.plugins:
            plugin_name = context.get_plugin_name(plugin_path)

            if not self._is_kebab_case(plugin_name):
                violations.append(
                    self.violation(
                        f"Plugin name '{plugin_name}' should use kebab-case",
                        file_path=plugin_path,
                    )
                )

        return violations

    @staticmethod
    def _is_kebab_case(name: str) -> bool:
        """Check if a name follows kebab-case convention"""
        return bool(re.match(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$", name))


class PluginReadmeRule(Rule):
    """Check that plugin has a README.md"""

    repo_types = PLUGIN_REPO_TYPES

    @property
    def rule_id(self) -> str:
        return "plugin-readme"

    @property
    def description(self) -> str:
        return "Plugin should have a README.md file"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    @property
    def llm_fix_prompt(self):
        return (
            "You are creating a README.md for a Claude Code plugin.\n\n"
            "Rules:\n"
            "- Read the plugin.json and any command/skill files to understand what the plugin does\n"
            "- Write a brief README with: plugin name as heading, one-line description, "
            "list of commands/skills, and basic usage\n"
            "- Keep it concise — under 50 lines\n"
            "- Use markdown formatting"
        )

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        for plugin_path in context.plugins:
            readme = plugin_path / "README.md"
            if not readme.exists():
                violations.append(
                    self.violation("Missing README.md (recommended)", file_path=readme)
                )

        return violations

"""
Rules for validating plugin structure
"""

import json
import re
from pathlib import Path
from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext


class PluginJsonRequiredRule(Rule):
    """Check that plugin.json exists"""

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

    DEFAULT_RECOMMENDED_FIELDS = ["description", "version", "author"]

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
            try:
                with open(plugin_json, "r") as f:
                    data = json.load(f)
            except json.JSONDecodeError as e:
                violations.append(self.violation(f"Invalid JSON: {e}", file_path=plugin_json))
                continue
            except IOError as e:
                violations.append(
                    self.violation(f"Failed to read file: {e}", file_path=plugin_json)
                )
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
                if not re.match(r"^\d+\.\d+\.\d+", str(version)):
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


class CommandsDirRequiredRule(Rule):
    """Check that commands directory exists"""

    @property
    def rule_id(self) -> str:
        return "commands-dir-required"

    @property
    def description(self) -> str:
        return "Plugin must have a commands directory"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        for plugin_path in context.plugins:
            commands_dir = plugin_path / "commands"
            if not commands_dir.exists():
                violations.append(
                    self.violation("Missing commands directory", file_path=plugin_path)
                )

        return violations


class CommandsExistRule(Rule):
    """Check that at least one command file exists"""

    @property
    def rule_id(self) -> str:
        return "commands-exist"

    @property
    def description(self) -> str:
        return "Plugin should have at least one command file"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        for plugin_path in context.plugins:
            commands_dir = plugin_path / "commands"

            if not commands_dir.exists():
                continue  # Handled by commands-dir-required

            command_files = list(commands_dir.glob("*.md"))
            if not command_files:
                violations.append(
                    self.violation(
                        "No command files found in commands directory",
                        file_path=commands_dir,
                    )
                )

        return violations


class PluginReadmeRule(Rule):
    """Check that plugin has a README.md"""

    @property
    def rule_id(self) -> str:
        return "plugin-readme"

    @property
    def description(self) -> str:
        return "Plugin should have a README.md file"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        for plugin_path in context.plugins:
            readme = plugin_path / "README.md"
            if not readme.exists():
                violations.append(
                    self.violation("Missing README.md (recommended)", file_path=plugin_path)
                )

        return violations

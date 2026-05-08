"""
Main linter orchestration
"""

import importlib.util
import os
import sys
from pathlib import Path
from typing import List, Dict, Type, Tuple

from .rule import Rule, RuleViolation, Severity
from .context import RepositoryContext
from .config import LinterConfig


class Linter:
    """
    Main linter that orchestrates rule checking
    """

    def __init__(self, context: RepositoryContext, config: LinterConfig = None):
        """
        Initialize linter

        Args:
            context: Repository context
            config: Linter configuration (uses default if None)
        """
        self.context = context
        self.config = config or LinterConfig.default()
        self.rules: List[Rule] = []
        self._load_rules()

    def _load_rules(self):
        """Load all enabled rules"""
        self._known_rule_ids: set = set()

        # Load builtin rules
        self._load_builtin_rules()

        # Load custom rules
        for custom_rule_path in self.config.custom_rules:
            self._load_custom_rule(custom_rule_path)

    def _load_builtin_rules(self):
        """Load builtin rules from skillsaw.rules.builtin"""
        from .rules.builtin import BUILTIN_RULES

        for rule_class in BUILTIN_RULES:
            # Instantiate to discover rule_id (a property, not accessible on the class)
            rule_instance = rule_class()
            self._known_rule_ids.add(rule_instance.rule_id)
            config = self.config.get_rule_config(rule_instance.rule_id)
            if config:
                rule_instance = rule_class(config)

            # Check if enabled for this context
            if self.config.is_rule_enabled(
                rule_instance.rule_id, self.context, rule_instance.repo_types
            ):
                self.rules.append(rule_instance)

    def _load_custom_rule(self, rule_path: str):
        """
        Load a custom rule from a Python file

        Args:
            rule_path: Path to Python file containing Rule subclass
        """
        path = Path(rule_path)
        # If relative path, resolve relative to repository root
        if not path.is_absolute():
            path = self.context.root_path / path
        path = path.resolve()

        if not path.exists():
            raise FileNotFoundError(f"Custom rule file not found: {path}")

        # Load the module
        spec = importlib.util.spec_from_file_location("custom_rule", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Find Rule subclasses in the module
        for name in dir(module):
            obj = getattr(module, name)
            if isinstance(obj, type) and issubclass(obj, Rule) and obj is not Rule:
                # Instantiate to discover rule_id (a property, not accessible on the class)
                rule_instance = obj()
                self._known_rule_ids.add(rule_instance.rule_id)
                config = self.config.get_rule_config(rule_instance.rule_id)
                if config:
                    rule_instance = obj(config)

                # Check if enabled
                if self.config.is_rule_enabled(
                    rule_instance.rule_id, self.context, rule_instance.repo_types
                ):
                    self.rules.append(rule_instance)

    def _validate_config(self) -> List[RuleViolation]:
        """Check for unknown rule IDs in config"""
        warnings = []
        for rule_id in self.config.rules:
            if rule_id not in self._known_rule_ids:
                warnings.append(
                    RuleViolation(
                        rule_id="invalid-config",
                        severity=Severity.WARNING,
                        message=f"Unknown rule '{rule_id}' in config — rule does not exist and will be ignored",
                    )
                )
        return warnings

    def run(self) -> List[RuleViolation]:
        """
        Run all enabled rules

        Returns:
            List of all violations found
        """
        violations = self._validate_config()

        for rule in self.rules:
            try:
                rule_violations = rule.check(self.context)
                violations.extend(rule_violations)
            except Exception as e:
                print(f"Error running rule {rule.rule_id}: {e}", file=sys.stderr)

        return violations

    def get_counts(self, violations: List[RuleViolation]) -> Tuple[int, int, int]:
        """
        Count violations by severity

        Args:
            violations: List of violations

        Returns:
            Tuple of (errors, warnings, info)
        """
        errors = sum(1 for v in violations if v.severity == Severity.ERROR)
        warnings = sum(1 for v in violations if v.severity == Severity.WARNING)
        info = sum(1 for v in violations if v.severity == Severity.INFO)
        return errors, warnings, info

    def format_results(self, violations: List[RuleViolation], verbose: bool = False) -> str:
        """
        Format violations for display

        Args:
            violations: List of violations
            verbose: Show info-level messages

        Returns:
            Formatted string
        """
        # Support NO_COLOR (https://no-color.org/)
        no_color = "NO_COLOR" in os.environ
        red = "" if no_color else "\033[91m"
        yellow = "" if no_color else "\033[93m"
        blue = "" if no_color else "\033[94m"
        green = "" if no_color else "\033[92m"
        bold = "" if no_color else "\033[1m"
        reset = "" if no_color else "\033[0m"

        errors, warnings, info = self.get_counts(violations)

        # Group by severity
        errors_list = [v for v in violations if v.severity == Severity.ERROR]
        warnings_list = [v for v in violations if v.severity == Severity.WARNING]
        info_list = [v for v in violations if v.severity == Severity.INFO]

        output = []

        # Print errors
        if errors_list:
            output.append(f"\n{red}{bold}Errors:{reset}")
            for v in errors_list:
                output.append(f"  {v}")

        # Print warnings
        if warnings_list:
            output.append(f"\n{yellow}{bold}Warnings:{reset}")
            for v in warnings_list:
                output.append(f"  {v}")

        # Print info (only in verbose)
        if verbose and info_list:
            output.append(f"\n{blue}{bold}Info:{reset}")
            for v in info_list:
                output.append(f"  {v}")

        # Summary
        output.append(f"\n{bold}Summary:{reset}")
        output.append(f"  {red}Errors:   {errors}{reset}")
        output.append(f"  {yellow}Warnings: {warnings}{reset}")
        if verbose:
            output.append(f"  {blue}Info:     {info}{reset}")

        if errors == 0 and warnings == 0:
            output.append(f"\n{green}{bold}✓ All checks passed!{reset}")

        return "\n".join(output)

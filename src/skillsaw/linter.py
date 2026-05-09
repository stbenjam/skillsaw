"""
Main linter orchestration
"""

import importlib.util
import sys
from pathlib import Path
from typing import List

from .rule import Rule, RuleViolation, Severity, AutofixResult, AutofixConfidence
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

    def fix(self) -> tuple[List[RuleViolation], List[AutofixResult]]:
        """
        Run all enabled rules and attempt to fix violations.

        Returns:
            Tuple of (remaining violations, autofix results)
        """
        all_violations = self._validate_config()
        all_fixes: List[AutofixResult] = []

        for rule in self.rules:
            try:
                rule_violations = rule.check(self.context)
            except Exception as e:
                print(f"Error running rule {rule.rule_id}: {e}", file=sys.stderr)
                continue

            if rule_violations and rule.supports_autofix:
                try:
                    fixes = rule.fix(self.context, rule_violations)
                    all_fixes.extend(fixes)
                    fixed_violations = {id(v) for fix in fixes for v in fix.violations_fixed}
                    remaining = [v for v in rule_violations if id(v) not in fixed_violations]
                    all_violations.extend(remaining)
                except Exception as e:
                    print(f"Error fixing rule {rule.rule_id}: {e}", file=sys.stderr)
                    all_violations.extend(rule_violations)
            else:
                all_violations.extend(rule_violations)

        return all_violations, all_fixes

    @staticmethod
    def apply_fixes(
        fixes: List[AutofixResult],
        confidence: AutofixConfidence = AutofixConfidence.SAFE,
    ) -> List[AutofixResult]:
        """
        Write fix results to disk.

        Args:
            fixes: Autofix results to apply
            confidence: Minimum confidence level to apply (SAFE = only safe,
                        SUGGEST = safe + suggest)

        Returns:
            List of fixes that were actually applied
        """
        applied: List[AutofixResult] = []
        allowed = {AutofixConfidence.SAFE}
        if confidence == AutofixConfidence.SUGGEST:
            allowed.add(AutofixConfidence.SUGGEST)

        for fix in fixes:
            if fix.confidence not in allowed:
                continue
            fix.file_path.write_text(fix.fixed_content, encoding="utf-8")
            applied.append(fix)

        return applied

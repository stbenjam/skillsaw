"""
Rule: promptfoo-assertions
"""

from pathlib import Path
from typing import Any, Dict, List

from skillsaw.context import RepositoryContext
from skillsaw.lint_target import PromptfooConfigNode
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.rules.builtin.utils import (
    commented_item_line,
    read_yaml_commented,
)

from ._helpers import (
    _PROMPTFOO_REPO_TYPES,
    _collect_tests,
    _get_assertion_types,
)


class PromptfooAssertionsRule(Rule):
    """Require specific assertion types in promptfoo eval tests"""

    repo_types = _PROMPTFOO_REPO_TYPES

    config_schema = {
        "required-types": {
            "type": "list",
            "default": [],
            "description": "Assertion types that every test must include (via test-level or defaultTest assertions)",
        },
        "threshold-constraints": {
            "type": "dict",
            "default": {},
            "description": "Per-assertion-type threshold bounds, e.g. {cost: {max: 2.0}, latency: {max: 30000}}",
        },
    }

    @property
    def rule_id(self) -> str:
        return "promptfoo-assertions"

    @property
    def description(self) -> str:
        return "Require specific assertion types in all promptfoo eval tests"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        required_types = set(
            self.config.get(
                "required-types",
                self.config_schema["required-types"]["default"],
            )
        )
        constraints = self.config.get(
            "threshold-constraints",
            self.config_schema["threshold-constraints"]["default"],
        )

        for node in context.lint_tree.find(PromptfooConfigNode):
            if node.is_fragment:
                continue

            data, error, _ = read_yaml_commented(node.path)
            if error or not isinstance(data, dict):
                continue

            default_test = data.get("defaultTest")
            default_types = _get_assertion_types(
                default_test.get("assert", []) if isinstance(default_test, dict) else []
            )

            if constraints and isinstance(default_test, dict):
                self._check_threshold_constraints(
                    default_test.get("assert", []),
                    "defaultTest",
                    constraints,
                    node.path,
                    violations,
                )

            all_tests = _collect_tests(node, context)

            for i, info in enumerate(all_tests):
                test = info.test
                test_types = _get_assertion_types(test.get("assert", []))
                desc = test.get("description", f"tests[{i}]")

                if required_types:
                    combined = default_types | test_types
                    missing = required_types - combined
                    if missing:
                        violations.append(
                            self.violation(
                                f"Test '{desc}' missing required assertion type(s): "
                                f"{', '.join(sorted(missing))}",
                                file_path=info.file_path,
                                line=info.line,
                            )
                        )

                if constraints:
                    self._check_threshold_constraints(
                        test.get("assert", []),
                        desc,
                        constraints,
                        info.file_path,
                        violations,
                    )

        return violations

    def _check_threshold_constraints(
        self,
        assert_list: Any,
        label: str,
        constraints: Dict[str, Any],
        config_path: Path,
        violations: List[RuleViolation],
    ) -> None:
        if not isinstance(assert_list, list):
            return
        for j, a in enumerate(assert_list):
            if not isinstance(a, dict):
                continue
            a_type = a.get("type")
            if not isinstance(a_type, str) or a_type not in constraints:
                continue
            threshold = a.get("threshold")
            if not isinstance(threshold, (int, float)):
                continue
            bounds = constraints[a_type]
            if not isinstance(bounds, dict):
                continue
            a_line = commented_item_line(assert_list, j)
            max_val = bounds.get("max")
            if isinstance(max_val, (int, float)) and threshold > max_val:
                violations.append(
                    self.violation(
                        f"'{label}' {a_type} threshold {threshold} exceeds "
                        f"max allowed {max_val}",
                        file_path=config_path,
                        line=a_line,
                    )
                )
            min_val = bounds.get("min")
            if isinstance(min_val, (int, float)) and threshold < min_val:
                violations.append(
                    self.violation(
                        f"'{label}' {a_type} threshold {threshold} below " f"min allowed {min_val}",
                        file_path=config_path,
                        line=a_line,
                    )
                )

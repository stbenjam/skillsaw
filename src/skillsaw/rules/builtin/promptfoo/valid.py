"""
Rule: promptfoo-valid
"""

from pathlib import Path
from typing import List, Optional

from skillsaw.context import RepositoryContext
from skillsaw.lint_target import PromptfooConfigNode
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.rules.builtin.utils import (
    commented_item_line,
    commented_key_line,
    read_yaml_commented,
)

from ._helpers import _PROMPTFOO_REPO_TYPES, _resolve_file_ref


class PromptfooValidRule(Rule):
    """Validate promptfoo eval YAML structure"""

    repo_types = _PROMPTFOO_REPO_TYPES

    @property
    def rule_id(self) -> str:
        return "promptfoo-valid"

    @property
    def description(self) -> str:
        return "Validate promptfoo eval YAML config structure and file references"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []

        for node in context.lint_tree.find(PromptfooConfigNode):
            data, error, error_line = read_yaml_commented(node.path)
            if error:
                violations.append(
                    self.violation(f"Invalid YAML: {error}", file_path=node.path, line=error_line)
                )
                continue

            if node.is_fragment:
                self._validate_fragment(data, node.path, violations)
            else:
                self._validate_config(data, node.path, violations)

        return violations

    def _validate_config(
        self, data: object, config_path: Path, violations: List[RuleViolation]
    ) -> None:
        if not isinstance(data, dict):
            violations.append(
                self.violation(
                    "Promptfoo config must be a YAML mapping",
                    file_path=config_path,
                )
            )
            return

        tests = data.get("tests")
        scenarios = data.get("scenarios")
        redteam = data.get("redteam")
        prompts = data.get("prompts")

        if tests is None and scenarios is None and redteam is None and prompts is None:
            violations.append(
                self.violation(
                    "No 'tests', 'scenarios', 'redteam', or 'prompts' found",
                    file_path=config_path,
                    severity=Severity.WARNING,
                )
            )
            return

        if redteam is not None and not isinstance(redteam, dict):
            violations.append(
                self.violation(
                    "'redteam' must be a mapping",
                    file_path=config_path,
                    line=commented_key_line(data, "redteam"),
                )
            )

        if scenarios is not None and not isinstance(scenarios, (list, str)):
            violations.append(
                self.violation(
                    "'scenarios' must be an array or a string file reference",
                    file_path=config_path,
                    line=commented_key_line(data, "scenarios"),
                )
            )

        if tests is not None:
            if isinstance(tests, str):
                self._check_file_ref_exists(
                    tests,
                    config_path,
                    violations,
                    line=commented_key_line(data, "tests"),
                )
            elif isinstance(tests, list):
                self._validate_test_list(tests, config_path, violations)
            elif isinstance(tests, dict):
                pass
            else:
                violations.append(
                    self.violation(
                        "'tests' must be an array or a string file reference",
                        file_path=config_path,
                        line=commented_key_line(data, "tests"),
                    )
                )

    def _validate_fragment(
        self, data: object, frag_path: Path, violations: List[RuleViolation]
    ) -> None:
        if isinstance(data, list):
            for i, test in enumerate(data):
                if not isinstance(test, dict):
                    violations.append(
                        self.violation(
                            f"tests[{i}] must be a mapping",
                            file_path=frag_path,
                            line=commented_item_line(data, i),
                        )
                    )
                    continue
                self._validate_test_assertions(test, i, frag_path, violations)
        elif isinstance(data, dict):
            self._validate_test_assertions(data, 0, frag_path, violations)
        else:
            violations.append(
                self.violation(
                    "Test fragment must be a mapping or a list of mappings",
                    file_path=frag_path,
                )
            )

    def _validate_test_list(
        self,
        tests: list,
        config_path: Path,
        violations: List[RuleViolation],
    ) -> None:
        for i, test in enumerate(tests):
            if isinstance(test, str):
                self._check_file_ref_exists(
                    test,
                    config_path,
                    violations,
                    line=commented_item_line(tests, i),
                )
                continue
            if not isinstance(test, dict):
                violations.append(
                    self.violation(
                        f"tests[{i}] must be a mapping or a string file reference",
                        file_path=config_path,
                        line=commented_item_line(tests, i),
                    )
                )
                continue
            self._validate_test_assertions(test, i, config_path, violations)

    def _validate_test_assertions(
        self,
        test: dict,
        index: int,
        file_path: Path,
        violations: List[RuleViolation],
    ) -> None:
        asserts = test.get("assert")
        if asserts is None:
            return
        if not isinstance(asserts, list):
            violations.append(
                self.violation(
                    f"tests[{index}] 'assert' must be an array",
                    file_path=file_path,
                    line=commented_key_line(test, "assert"),
                )
            )
            return
        for j, a in enumerate(asserts):
            if not isinstance(a, dict):
                violations.append(
                    self.violation(
                        f"tests[{index}].assert[{j}] must be a mapping",
                        file_path=file_path,
                        line=commented_item_line(asserts, j),
                    )
                )
                continue
            if "$ref" in a:
                continue
            if "type" not in a:
                violations.append(
                    self.violation(
                        f"tests[{index}].assert[{j}] missing required 'type'",
                        file_path=file_path,
                        line=commented_item_line(asserts, j),
                    )
                )

    def _check_file_ref_exists(
        self,
        ref: str,
        config_path: Path,
        violations: List[RuleViolation],
        line: Optional[int] = None,
    ) -> None:
        resolved = _resolve_file_ref(ref, config_path.parent)
        if resolved is None:
            return
        if not resolved.exists():
            violations.append(
                self.violation(
                    f"File reference '{ref}' not found",
                    file_path=config_path,
                    line=line,
                )
            )

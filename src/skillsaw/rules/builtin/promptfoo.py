"""
Rules for validating promptfoo eval configurations.

Discovers *.yaml / *.yml files inside evals/ directories of plugins and skills,
validates their structure, and optionally enforces assertion-type and metadata
policies.
"""

from pathlib import Path
from typing import Any, Dict, List, Set

from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.lint_target import PluginNode, SkillNode
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.rules.builtin.utils import read_yaml

_SKILL_REPO_TYPES = {
    RepositoryType.SINGLE_PLUGIN,
    RepositoryType.MARKETPLACE,
    RepositoryType.AGENTSKILLS,
    RepositoryType.DOT_CLAUDE,
}


def _find_promptfoo_configs(context: RepositoryContext) -> List[Path]:
    """Find promptfoo YAML configs in evals/ directories of plugins and skills."""
    configs: List[Path] = []
    seen: Set[Path] = set()

    for node in context.lint_tree.find(PluginNode) + context.lint_tree.find(SkillNode):
        evals_dir = node.path / "evals"
        if not evals_dir.is_dir():
            continue
        for pattern in ("*.yaml", "*.yml"):
            for yaml_file in sorted(evals_dir.glob(pattern)):
                resolved = yaml_file.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    configs.append(yaml_file)
    return configs


def _get_assertion_types(assert_list: Any) -> Set[str]:
    """Extract assertion type strings from an assert array."""
    types: Set[str] = set()
    if not isinstance(assert_list, list):
        return types
    for item in assert_list:
        if isinstance(item, dict) and isinstance(item.get("type"), str):
            types.add(item["type"])
    return types


class PromptfooValidRule(Rule):
    """Validate promptfoo eval YAML structure"""

    repo_types = _SKILL_REPO_TYPES

    @property
    def rule_id(self) -> str:
        return "promptfoo-valid"

    @property
    def description(self) -> str:
        return "Validate promptfoo eval YAML configs in evals/ directories"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []

        for config_path in _find_promptfoo_configs(context):
            data, error = read_yaml(config_path)
            if error:
                violations.append(self.violation(f"Invalid YAML: {error}", file_path=config_path))
                continue

            if not isinstance(data, dict):
                violations.append(
                    self.violation(
                        "Promptfoo config must be a YAML mapping",
                        file_path=config_path,
                    )
                )
                continue

            tests = data.get("tests")
            if tests is None:
                violations.append(
                    self.violation("Missing required 'tests' key", file_path=config_path)
                )
                continue

            if not isinstance(tests, list):
                violations.append(self.violation("'tests' must be an array", file_path=config_path))
                continue

            for i, test in enumerate(tests):
                if not isinstance(test, dict):
                    violations.append(
                        self.violation(f"tests[{i}] must be a mapping", file_path=config_path)
                    )
                    continue

                if "description" not in test:
                    violations.append(
                        self.violation(
                            f"tests[{i}] missing 'description'",
                            file_path=config_path,
                            severity=Severity.WARNING,
                        )
                    )

                asserts = test.get("assert")
                if asserts is not None and not isinstance(asserts, list):
                    violations.append(
                        self.violation(
                            f"tests[{i}] 'assert' must be an array", file_path=config_path
                        )
                    )
                elif isinstance(asserts, list):
                    for j, a in enumerate(asserts):
                        if isinstance(a, dict) and "type" not in a:
                            violations.append(
                                self.violation(
                                    f"tests[{i}].assert[{j}] missing required 'type'",
                                    file_path=config_path,
                                )
                            )

        return violations


class PromptfooAssertionsRule(Rule):
    """Require specific assertion types in promptfoo eval tests"""

    repo_types = _SKILL_REPO_TYPES

    config_schema = {
        "required-types": {
            "type": "list",
            "default": ["cost", "latency"],
            "description": "Assertion types that every test must include (via test-level or defaultTest assertions)",
        },
        "max-cost-threshold": {
            "type": "float",
            "default": None,
            "description": "Maximum allowed value for cost assertion thresholds (budget cap)",
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
            self.config.get("required-types", self.config_schema["required-types"]["default"])
        )
        max_cost = self.config.get("max-cost-threshold")

        for config_path in _find_promptfoo_configs(context):
            data, error = read_yaml(config_path)
            if error or not isinstance(data, dict):
                continue

            tests = data.get("tests")
            if not isinstance(tests, list):
                continue

            default_test = data.get("defaultTest")
            default_types = _get_assertion_types(
                default_test.get("assert", []) if isinstance(default_test, dict) else []
            )

            if max_cost is not None and isinstance(default_test, dict):
                self._check_cost_thresholds(
                    default_test.get("assert", []),
                    "defaultTest",
                    max_cost,
                    config_path,
                    violations,
                )

            for i, test in enumerate(tests):
                if not isinstance(test, dict):
                    continue

                test_types = _get_assertion_types(test.get("assert", []))
                combined = default_types | test_types
                missing = required_types - combined
                if missing:
                    desc = test.get("description", f"tests[{i}]")
                    violations.append(
                        self.violation(
                            f"Test '{desc}' missing required assertion type(s): "
                            f"{', '.join(sorted(missing))}",
                            file_path=config_path,
                        )
                    )

                if max_cost is not None:
                    desc = test.get("description", f"tests[{i}]")
                    self._check_cost_thresholds(
                        test.get("assert", []), desc, max_cost, config_path, violations
                    )

        return violations

    @staticmethod
    def _check_cost_thresholds(
        assert_list: Any,
        label: str,
        max_cost: float,
        config_path: Path,
        violations: List[RuleViolation],
    ) -> None:
        if not isinstance(assert_list, list):
            return
        for a in assert_list:
            if not isinstance(a, dict) or a.get("type") != "cost":
                continue
            threshold = a.get("threshold")
            if isinstance(threshold, (int, float)) and threshold > max_cost:
                violations.append(
                    RuleViolation(
                        rule_id="promptfoo-assertions",
                        message=(
                            f"'{label}' cost threshold {threshold} exceeds "
                            f"max allowed {max_cost}"
                        ),
                        file_path=config_path,
                        severity=Severity.WARNING,
                    )
                )


class PromptfooMetadataRule(Rule):
    """Require specific metadata keys on promptfoo eval tests"""

    repo_types = _SKILL_REPO_TYPES

    config_schema = {
        "required-keys": {
            "type": "list",
            "default": ["token-usage", "tier"],
            "description": "Metadata keys required on every test case",
        },
    }

    @property
    def rule_id(self) -> str:
        return "promptfoo-metadata"

    @property
    def description(self) -> str:
        return "Require specific metadata keys on all promptfoo eval tests"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        required_keys = set(
            self.config.get("required-keys", self.config_schema["required-keys"]["default"])
        )

        for config_path in _find_promptfoo_configs(context):
            data, error = read_yaml(config_path)
            if error or not isinstance(data, dict):
                continue

            tests = data.get("tests")
            if not isinstance(tests, list):
                continue

            for i, test in enumerate(tests):
                if not isinstance(test, dict):
                    continue

                metadata = test.get("metadata")
                desc = test.get("description", f"tests[{i}]")

                if metadata is None:
                    violations.append(
                        self.violation(
                            f"Test '{desc}' missing 'metadata' "
                            f"(required keys: {', '.join(sorted(required_keys))})",
                            file_path=config_path,
                        )
                    )
                    continue

                if not isinstance(metadata, dict):
                    violations.append(
                        self.violation(
                            f"Test '{desc}' 'metadata' must be a mapping",
                            file_path=config_path,
                        )
                    )
                    continue

                missing = required_keys - set(metadata.keys())
                if missing:
                    violations.append(
                        self.violation(
                            f"Test '{desc}' missing required metadata key(s): "
                            f"{', '.join(sorted(missing))}",
                            file_path=config_path,
                        )
                    )

        return violations

"""
Rules for validating promptfoo eval configurations.

Discovers promptfoo config files (promptfooconfig*.yaml, evals/*.yaml) and
test fragment files referenced via file://, validates their structure, and
optionally enforces assertion-type and metadata policies.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.lint_target import PromptfooConfigNode
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.rules.builtin.utils import read_yaml

_PROMPTFOO_KEYS = frozenset(
    {"providers", "prompts", "tests", "scenarios", "defaultTest", "evaluateOptions"}
)

_SKILL_REPO_TYPES = {
    RepositoryType.SINGLE_PLUGIN,
    RepositoryType.MARKETPLACE,
    RepositoryType.AGENTSKILLS,
    RepositoryType.DOT_CLAUDE,
    RepositoryType.PROMPTFOO,
}

_NON_YAML_EXTENSIONS = frozenset({".csv", ".xlsx", ".xls", ".js", ".ts", ".py", ".json", ".jsonl"})


def _is_promptfoo_config(data: object) -> bool:
    """True if data is a mapping with at least one promptfoo-specific key."""
    return isinstance(data, dict) and bool(_PROMPTFOO_KEYS & set(data.keys()))


def _resolve_file_ref(ref: str, config_dir: Path) -> Optional[Path]:
    """Resolve a file:// reference relative to config_dir.

    Returns the resolved path (which may or may not exist on disk).
    Returns None for glob patterns, non-YAML extensions, and remote URLs.
    """
    if not ref.startswith("file://"):
        if ref.startswith(("http://", "https://", "huggingface://")):
            return None
        raw = ref
    else:
        raw = ref[len("file://") :]

    if not raw:
        return None
    if any(c in raw for c in ("*", "?")):
        return None

    suffix = Path(raw).suffix.lower()
    if suffix in _NON_YAML_EXTENSIONS:
        return None
    if suffix not in (".yaml", ".yml"):
        return None

    return (config_dir / raw).resolve()


def _extract_file_refs(data: dict) -> List[str]:
    """Extract string file references from a parsed promptfoo config's tests field."""
    refs: List[str] = []
    tests = data.get("tests")
    if isinstance(tests, str):
        refs.append(tests)
    elif isinstance(tests, list):
        for entry in tests:
            if isinstance(entry, str):
                refs.append(entry)
    return refs


def _get_assertion_types(assert_list: Any) -> Set[str]:
    types: Set[str] = set()
    if not isinstance(assert_list, list):
        return types
    for item in assert_list:
        if isinstance(item, dict) and isinstance(item.get("type"), str):
            types.add(item["type"])
    return types


def _collect_tests(node: PromptfooConfigNode, context: RepositoryContext) -> List[dict]:
    """Collect all test dicts reachable from a full config node, including fragments."""
    data, error = read_yaml(node.path)
    if error or not isinstance(data, dict):
        return []

    tests: List[dict] = []
    raw_tests = data.get("tests")
    if isinstance(raw_tests, list):
        tests.extend(t for t in raw_tests if isinstance(t, dict))

    for child in node.find(PromptfooConfigNode):
        if child is node:
            continue
        if not child.is_fragment:
            continue
        frag_data, frag_err = read_yaml(child.path)
        if frag_err:
            continue
        if isinstance(frag_data, list):
            tests.extend(t for t in frag_data if isinstance(t, dict))
        elif isinstance(frag_data, dict):
            tests.append(frag_data)

    return tests


class PromptfooValidRule(Rule):
    """Validate promptfoo eval YAML structure"""

    repo_types = _SKILL_REPO_TYPES

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
            data, error = read_yaml(node.path)
            if error:
                violations.append(self.violation(f"Invalid YAML: {error}", file_path=node.path))
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

        if tests is None and scenarios is None:
            violations.append(
                self.violation(
                    "No 'tests' or 'scenarios' found",
                    file_path=config_path,
                    severity=Severity.WARNING,
                )
            )
            return

        if scenarios is not None and not isinstance(scenarios, (list, str)):
            violations.append(
                self.violation(
                    "'scenarios' must be an array or a string file reference",
                    file_path=config_path,
                )
            )

        if tests is not None:
            if isinstance(tests, str):
                self._check_file_ref_exists(tests, config_path, violations)
            elif isinstance(tests, list):
                self._validate_test_list(tests, config_path, violations)
            else:
                violations.append(
                    self.violation(
                        "'tests' must be an array or a string file reference",
                        file_path=config_path,
                    )
                )

    def _validate_fragment(
        self, data: object, frag_path: Path, violations: List[RuleViolation]
    ) -> None:
        if isinstance(data, list):
            for i, test in enumerate(data):
                if not isinstance(test, dict):
                    violations.append(
                        self.violation(f"tests[{i}] must be a mapping", file_path=frag_path)
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
                self._check_file_ref_exists(test, config_path, violations)
                continue
            if not isinstance(test, dict):
                violations.append(
                    self.violation(
                        f"tests[{i}] must be a mapping or a string file reference",
                        file_path=config_path,
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
                )
            )
            return
        for j, a in enumerate(asserts):
            if not isinstance(a, dict):
                violations.append(
                    self.violation(
                        f"tests[{index}].assert[{j}] must be a mapping",
                        file_path=file_path,
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
                    )
                )

    def _check_file_ref_exists(
        self, ref: str, config_path: Path, violations: List[RuleViolation]
    ) -> None:
        resolved = _resolve_file_ref(ref, config_path.parent)
        if resolved is None:
            return
        if not resolved.exists():
            violations.append(
                self.violation(
                    f"File reference '{ref}' not found",
                    file_path=config_path,
                )
            )


class PromptfooAssertionsRule(Rule):
    """Require specific assertion types in promptfoo eval tests"""

    repo_types = _SKILL_REPO_TYPES

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

            data, error = read_yaml(node.path)
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

            for i, test in enumerate(all_tests):
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
                                file_path=node.path,
                            )
                        )

                if constraints:
                    self._check_threshold_constraints(
                        test.get("assert", []),
                        desc,
                        constraints,
                        node.path,
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
        for a in assert_list:
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
            max_val = bounds.get("max")
            if isinstance(max_val, (int, float)) and threshold > max_val:
                violations.append(
                    self.violation(
                        f"'{label}' {a_type} threshold {threshold} exceeds "
                        f"max allowed {max_val}",
                        file_path=config_path,
                    )
                )
            min_val = bounds.get("min")
            if isinstance(min_val, (int, float)) and threshold < min_val:
                violations.append(
                    self.violation(
                        f"'{label}' {a_type} threshold {threshold} below " f"min allowed {min_val}",
                        file_path=config_path,
                    )
                )


class PromptfooMetadataRule(Rule):
    """Require specific metadata keys on promptfoo eval tests"""

    repo_types = _SKILL_REPO_TYPES

    config_schema = {
        "required-keys": {
            "type": "list",
            "default": [],
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
            self.config.get(
                "required-keys",
                self.config_schema["required-keys"]["default"],
            )
        )

        for node in context.lint_tree.find(PromptfooConfigNode):
            if node.is_fragment:
                continue

            all_tests = _collect_tests(node, context)

            for i, test in enumerate(all_tests):
                metadata = test.get("metadata")
                desc = test.get("description", f"tests[{i}]")

                if metadata is None:
                    if required_keys:
                        violations.append(
                            self.violation(
                                f"Test '{desc}' missing 'metadata' "
                                f"(required keys: {', '.join(sorted(required_keys))})",
                                file_path=node.path,
                            )
                        )
                    continue

                if not isinstance(metadata, dict):
                    violations.append(
                        self.violation(
                            f"Test '{desc}' 'metadata' must be a mapping",
                            file_path=node.path,
                        )
                    )
                    continue

                if required_keys:
                    missing = required_keys - set(metadata.keys())
                    if missing:
                        violations.append(
                            self.violation(
                                f"Test '{desc}' missing required metadata key(s): "
                                f"{', '.join(sorted(missing))}",
                                file_path=node.path,
                            )
                        )

        return violations

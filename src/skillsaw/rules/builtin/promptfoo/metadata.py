"""
Rule: promptfoo-metadata
"""

from typing import Any, Dict, List

from skillsaw.context import RepositoryContext
from skillsaw.lint_target import PromptfooConfigNode
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.rules.builtin.utils import (
    commented_key_line,
    read_yaml_commented,
)

from ._helpers import _PROMPTFOO_REPO_TYPES, _collect_tests


class PromptfooMetadataRule(Rule):
    """Require specific metadata keys on promptfoo eval tests"""

    repo_types = _PROMPTFOO_REPO_TYPES

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

            data, error, _ = read_yaml_commented(node.path)
            if error or not isinstance(data, dict):
                continue

            default_test = data.get("defaultTest")
            default_metadata: Dict[str, Any] = {}
            if isinstance(default_test, dict):
                dm = default_test.get("metadata")
                if isinstance(dm, dict):
                    default_metadata = dm

            all_tests = _collect_tests(node, context)

            for i, info in enumerate(all_tests):
                test = info.test
                test_metadata = test.get("metadata")
                desc = test.get("description", f"tests[{i}]")

                if test_metadata is None and not default_metadata:
                    if required_keys:
                        violations.append(
                            self.violation(
                                f"Test '{desc}' missing 'metadata' "
                                f"(required keys: {', '.join(sorted(required_keys))})",
                                file_path=info.file_path,
                                line=info.line,
                            )
                        )
                    continue

                if test_metadata is not None and not isinstance(test_metadata, dict):
                    violations.append(
                        self.violation(
                            f"Test '{desc}' 'metadata' must be a mapping",
                            file_path=info.file_path,
                            line=commented_key_line(test, "metadata") or info.line,
                        )
                    )
                    continue

                combined_metadata = {**default_metadata, **(test_metadata or {})}

                if required_keys:
                    missing = required_keys - set(combined_metadata.keys())
                    if missing:
                        violations.append(
                            self.violation(
                                f"Test '{desc}' missing required metadata key(s): "
                                f"{', '.join(sorted(missing))}",
                                file_path=info.file_path,
                                line=commented_key_line(test, "metadata") or info.line,
                            )
                        )

        return violations

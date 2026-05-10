"""
Rules for validating .coderabbit.yaml configuration files.

CodeRabbit config files contain ``instructions`` fields consumed by an LLM.
The YAML structure is validated here; instruction text quality is checked by
the shared content-* rules via ``_get_body()`` in ``content_analysis.py``.
"""

from __future__ import annotations

from typing import List, Optional

import yaml

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.lint_target import CodeRabbitNode
from skillsaw.rules.builtin.utils import read_text

# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


class CoderabbitYamlValidRule(Rule):
    """Validate that .coderabbit.yaml is valid YAML"""

    repo_types = {RepositoryType.CODERABBIT}

    @property
    def rule_id(self) -> str:
        return "coderabbit-yaml-valid"

    @property
    def description(self) -> str:
        return ".coderabbit.yaml must be valid YAML"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []

        cr_nodes = context.lint_tree.find(CodeRabbitNode)
        if not cr_nodes:
            return violations

        cr_path = cr_nodes[0].path

        raw = read_text(cr_path)
        if raw is None:
            violations.append(
                self.violation(
                    "Failed to read .coderabbit.yaml (invalid encoding or I/O error)",
                    file_path=cr_path,
                )
            )
            return violations

        try:
            data = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            line: Optional[int] = None
            if hasattr(exc, "problem_mark") and exc.problem_mark is not None:
                line = exc.problem_mark.line + 1
            violations.append(
                self.violation(
                    f"Invalid YAML in .coderabbit.yaml: {exc}",
                    file_path=cr_path,
                    line=line,
                )
            )
            return violations

        if not isinstance(data, dict):
            violations.append(
                self.violation(
                    ".coderabbit.yaml must be a YAML mapping at the top level",
                    file_path=cr_path,
                )
            )

        return violations

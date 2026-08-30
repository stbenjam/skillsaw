"""Validate optional Devin-native SKILL.md frontmatter."""

from __future__ import annotations

from typing import Any, List, Optional

from skillsaw.blocks import DevinSkillBlock
from skillsaw.context import HAS_DEVIN, RepositoryContext
from skillsaw.formats import devin
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.utils import yaml_path_line_lookup


class DevinSkillValidRule(Rule):
    """Check Devin's optional skill fields without imposing the portable dialect."""

    since = "0.20.0"
    formats = frozenset({HAS_DEVIN})

    @property
    def rule_id(self) -> str:
        return "devin-skill-valid"

    @property
    def description(self) -> str:
        return "Devin-native SKILL.md frontmatter must use Devin's documented field shapes"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        for block in context.lint_tree.find(DevinSkillBlock):
            if block.frontmatter_error:
                violations.append(
                    self.violation(
                        block.frontmatter_error,
                        file_path=block.path,
                        line=block.frontmatter_error_line,
                        block=block,
                    )
                )
                continue
            if not block.has_frontmatter:
                # Devin defaults the skill name from its directory and makes
                # every frontmatter field optional.
                continue

            line_for = yaml_path_line_lookup(block.read_frontmatter_text(), line_offset=1)
            for key in ("name", "description", "argument-hint", "model", "agent"):
                violations.extend(self._check_string(block, key))
            violations.extend(self._check_bool(block, "subagent"))
            violations.extend(
                self._check_string_list(block, "allowed-tools", line_for, allow_scalar=True)
            )
            violations.extend(self._check_permissions(block, line_for))
            violations.extend(self._check_triggers(block, line_for))

            agent = block.field("agent")
            subagent = block.field("subagent")
            if (
                agent is not None
                and isinstance(agent.value, str)
                and agent.value.strip()
                and subagent is not None
                and subagent.value is True
            ):
                violations.append(
                    self.violation(
                        "Both 'agent' and 'subagent: true' are set; Devin uses the named "
                        "'agent' profile and ignores the default subagent selection",
                        file_path=block.path,
                        line=agent.field_line,
                        block=block,
                        severity=Severity.INFO,
                    )
                )

        return violations

    def _check_string(self, block: DevinSkillBlock, key: str) -> List[RuleViolation]:
        field = block.field(key)
        if field is None:
            return []
        if isinstance(field.value, str):
            return []
        return [
            self.violation(
                f"'{key}' must be a string, got {type(field.value).__name__}",
                file_path=block.path,
                line=field.field_line,
                block=block,
            )
        ]

    def _check_bool(self, block: DevinSkillBlock, key: str) -> List[RuleViolation]:
        field = block.field(key)
        if field is None or isinstance(field.value, bool):
            return []
        return [
            self.violation(
                f"'{key}' must be a boolean, got {type(field.value).__name__}",
                file_path=block.path,
                line=field.field_line,
                block=block,
            )
        ]

    def _check_string_list(
        self,
        block: DevinSkillBlock,
        key: str,
        line_for,
        *,
        path_prefix: Optional[str] = None,
        allow_scalar: bool = False,
    ) -> List[RuleViolation]:
        field = block.field(key) if path_prefix is None else None
        value: Any
        line: Optional[int]
        display = path_prefix or key
        if path_prefix is None:
            if field is None:
                return []
            value = field.value
            line = field.field_line
        else:
            permissions = block.field_value("permissions")
            if not isinstance(permissions, dict) or key not in permissions:
                return []
            value = permissions[key]
            line = line_for(path_prefix)

        if allow_scalar and isinstance(value, str):
            return []
        if not isinstance(value, list):
            expected = "a string or a list of strings" if allow_scalar else "a list of strings"
            return [
                self.violation(
                    f"'{display}' must be {expected}",
                    file_path=block.path,
                    line=line,
                    block=block,
                )
            ]

        violations: List[RuleViolation] = []
        for index, item in enumerate(value):
            if isinstance(item, str):
                continue
            violations.append(
                self.violation(
                    f"'{display}[{index}]' must be a string, got {type(item).__name__}",
                    file_path=block.path,
                    line=line_for(f"{display}[{index}]") or line,
                    block=block,
                )
            )
        return violations

    def _check_permissions(self, block: DevinSkillBlock, line_for) -> List[RuleViolation]:
        field = block.field("permissions")
        if field is None:
            return []
        if not isinstance(field.value, dict):
            return [
                self.violation(
                    "'permissions' must be an object",
                    file_path=block.path,
                    line=field.field_line,
                    block=block,
                )
            ]

        violations: List[RuleViolation] = []
        for key in devin.PERMISSION_KEYS:
            violations.extend(
                self._check_string_list(
                    block,
                    key,
                    line_for,
                    path_prefix=f"permissions.{key}",
                )
            )
        return violations

    def _check_triggers(self, block: DevinSkillBlock, line_for) -> List[RuleViolation]:
        field = block.field("triggers")
        if field is None:
            return []
        value = field.value
        if not isinstance(value, list) or not value:
            return [
                self.violation(
                    "'triggers' must be a non-empty list containing 'user' and/or 'model'",
                    file_path=block.path,
                    line=field.field_line,
                    block=block,
                )
            ]

        violations: List[RuleViolation] = []
        for index, trigger in enumerate(value):
            if isinstance(trigger, str) and trigger in devin.SKILL_TRIGGERS:
                continue
            violations.append(
                self.violation(
                    f"'triggers[{index}]' must be 'user' or 'model'",
                    file_path=block.path,
                    line=line_for(f"triggers[{index}]") or field.field_line,
                    block=block,
                )
            )
        return violations

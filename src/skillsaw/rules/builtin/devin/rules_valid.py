"""Validate Devin and legacy Windsurf workspace rules."""

from __future__ import annotations

from typing import List

from skillsaw.blocks import DevinRuleBlock
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.diagnostics import safe_display
from skillsaw.formats import devin
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.utils import read_text, yaml_path_line_lookup


def _absolute_glob(pattern: str) -> bool:
    """Recognize POSIX and Windows absolute paths on every host OS."""
    drive_path = len(pattern) > 2 and pattern[0].isalpha() and pattern[1] == ":"
    return pattern.startswith(("/", "\\", "~/")) or drive_path


class DevinRulesValidRule(Rule):
    """Check that Devin workspace rules parse and can activate."""

    since = "0.20.0"
    repo_types = frozenset({RepositoryType.DEVIN})

    config_schema = {
        "max-characters": {
            "type": "int",
            "default": devin.WORKSPACE_RULE_MAX_CHARACTERS,
            "description": "Maximum characters in one Devin Desktop workspace rule",
        }
    }

    @property
    def rule_id(self) -> str:
        return "devin-rules-valid"

    @property
    def description(self) -> str:
        return "Devin workspace rules must have valid activation frontmatter and fit its size limit"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        max_characters = self.setting("max-characters")
        if (
            isinstance(max_characters, bool)
            or not isinstance(max_characters, int)
            or max_characters <= 0
        ):
            max_characters = devin.WORKSPACE_RULE_MAX_CHARACTERS

        for block in context.lint_tree.find(DevinRuleBlock):
            content = read_text(block.path)
            if content is not None and len(content) > max_characters:
                violations.append(
                    self.violation(
                        f"Workspace rule exceeds {max_characters:,} characters "
                        f"({len(content):,})",
                        file_path=block.path,
                    )
                )

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

            field_errors = self._check_field_shapes(block)
            violations.extend(field_errors)
            if field_errors:
                continue

            trigger_field = block.field("trigger")
            if trigger_field is None or trigger_field.value is None:
                violations.extend(self._check_inferred_activation(block))
                continue

            trigger = trigger_field.value
            if not isinstance(trigger, str):
                violations.append(
                    self.violation(
                        f"'trigger' must be a string, got {type(trigger).__name__}",
                        file_path=block.path,
                        line=trigger_field.field_line,
                        block=block,
                    )
                )
                continue
            if trigger not in devin.RULE_TRIGGERS:
                expected = ", ".join(sorted(devin.RULE_TRIGGERS))
                violations.append(
                    self.violation(
                        f"Unsupported trigger {safe_display(trigger)!r}; expected one of: {expected}",
                        file_path=block.path,
                        line=trigger_field.field_line,
                        block=block,
                    )
                )
                continue

            if trigger == "glob":
                violations.extend(self._check_globs(block))
            elif trigger == "model_decision":
                violations.extend(self._check_model_description(block))

        return violations

    def _check_field_shapes(self, block: DevinRuleBlock) -> List[RuleViolation]:
        """The CLI decodes optional fields even when the selected mode ignores them."""
        violations: List[RuleViolation] = []
        description = block.field("description")
        if description is not None and isinstance(description.value, (dict, list, set, tuple)):
            violations.append(
                self.violation(
                    "'description' must be a scalar value or null",
                    file_path=block.path,
                    line=description.field_line,
                    block=block,
                )
            )
        globs = block.field("globs")
        if globs is not None and globs.value is not None:
            value = globs.value
            if isinstance(value, str):
                message = (
                    "'globs' must be a YAML list of strings — Devin Desktop may accept a "
                    "single string, but the Devin CLI fails to load the rule "
                    '("expected a sequence")'
                )
            elif not isinstance(value, list) or any(
                item is None or isinstance(item, (dict, list, set, tuple)) for item in value
            ):
                message = "'globs' must be a YAML list of scalar patterns or null"
            else:
                return violations
            violations.append(
                self.violation(
                    message,
                    file_path=block.path,
                    line=globs.field_line,
                    block=block,
                )
            )
        return violations

    def _check_inferred_activation(self, block: DevinRuleBlock) -> List[RuleViolation]:
        """A rule without ``trigger`` still activates the way Devin infers it.

        Devin reads ``trigger`` as optional and infers the mode the way
        Cursor does: ``globs`` makes the rule glob-activated, a
        ``description`` makes it agent-decidable, and a rule with neither
        is manual. Absent, null and empty globs do not select glob mode.
        A rule that never activates on its own is information, not an error —
        ``@rule`` invocation is a supported way to use it.
        """
        globs = block.field("globs")
        if globs is not None and globs.value:
            return self._check_globs(block)
        description = block.field("description")
        if description is not None and isinstance(description.value, str):
            if description.value.strip():
                return []
        return [
            self.violation(
                "Rule never activates on its own: set 'trigger: always_on', add "
                "'globs' to auto-attach, or add a 'description' so the agent can "
                "request it. Ignore this if the rule is meant to be invoked "
                "manually with @" + block.path.stem,
                file_path=block.path,
                block=block,
                severity=Severity.INFO,
            )
        ]

    def _check_model_description(self, block: DevinRuleBlock) -> List[RuleViolation]:
        field = block.field("description")
        if field is None or not isinstance(field.value, str) or not field.value.strip():
            return [
                self.violation(
                    "A model_decision rule requires a non-empty string 'description'",
                    file_path=block.path,
                    line=field.field_line if field is not None else None,
                    block=block,
                )
            ]
        return []

    def _check_globs(self, block: DevinRuleBlock) -> List[RuleViolation]:
        field = block.field("globs")
        if field is None or field.value is None:
            return [
                self.violation(
                    "A glob rule requires a non-empty 'globs' pattern",
                    file_path=block.path,
                    line=field.field_line if field is not None else None,
                    block=block,
                )
            ]

        # Keep the existing active-glob string contract; unused scalar items
        # are left to Devin's YAML coercion rather than newly rejected.
        patterns = field.value
        if not all(isinstance(pattern, str) for pattern in patterns):
            return [
                self.violation(
                    "'globs' must be a YAML list of strings",
                    file_path=block.path,
                    line=field.field_line,
                    block=block,
                )
            ]
        violations: List[RuleViolation] = []
        if not patterns:
            return [
                self.violation(
                    "'globs' must contain at least one pattern",
                    file_path=block.path,
                    line=field.field_line,
                    block=block,
                )
            ]

        line_for = yaml_path_line_lookup(block.read_frontmatter_text(), line_offset=1)
        for index, pattern in enumerate(patterns):
            where = f"globs[{index}]" if len(patterns) > 1 else "globs"
            line = line_for(f"globs[{index}]") or field.field_line
            stripped = pattern.strip()
            if not stripped:
                violations.append(
                    self.violation(
                        f"{where}: empty glob pattern",
                        file_path=block.path,
                        line=line,
                        block=block,
                    )
                )
                continue
            if _absolute_glob(stripped):
                violations.append(
                    self.violation(
                        f"{where}: {safe_display(stripped)!r} must be repository-relative, "
                        "not absolute",
                        file_path=block.path,
                        line=line,
                        block=block,
                    )
                )
                continue
            if ".." in stripped.replace("\\", "/").split("/"):
                violations.append(
                    self.violation(
                        f"{where}: {safe_display(stripped)!r} must not contain '..' segments",
                        file_path=block.path,
                        line=line,
                        block=block,
                    )
                )

        return violations

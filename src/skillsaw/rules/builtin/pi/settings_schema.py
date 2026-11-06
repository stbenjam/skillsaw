"""Validate project .pi/settings.json against Pi's published settings schema."""

from functools import lru_cache
from typing import TYPE_CHECKING, List

from skillsaw.blocks.pi import PiSettingsBlock
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.formats.pi import SETTINGS_RESOURCE_KEYS, SETTINGS_SCHEMA_VERSION, settings_schema
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.rules.builtin.agent_plugins._helpers import schema_error_summary

if TYPE_CHECKING:
    from jsonschema import Draft202012Validator


@lru_cache(maxsize=1)
def _validator() -> "Draft202012Validator":
    # Deferred: jsonschema costs ~20ms to import and only Pi projects need it.
    from jsonschema import Draft202012Validator

    return Draft202012Validator(settings_schema())


class PiSettingsSchemaRule(Rule):
    """Check non-resource settings against the bundled Pi settings schema."""

    since = "0.22.0"
    default_enabled = False
    repo_types = frozenset({RepositoryType.PI})

    @property
    def rule_id(self) -> str:
        return "pi-settings-schema"

    @property
    def description(self) -> str:
        return f"Pi project settings should match the Pi {SETTINGS_SCHEMA_VERSION} settings schema"

    def default_severity(self) -> Severity:
        # Pi does not validate settings files: a mistyped value is read as-is
        # and misbehaves at runtime instead of stopping Pi.
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        for block in context.lint_tree.find(PiSettingsBlock):
            data = block.raw_data
            # pi-config-valid reports parse errors and non-object documents.
            if block.parse_error or not isinstance(data, dict):
                continue
            errors = [
                error
                for error in _validator().iter_errors(data)
                if not error.absolute_path or error.absolute_path[0] not in SETTINGS_RESOURCE_KEYS
            ]
            if errors:
                violations.append(
                    self.violation(
                        f"Pi settings do not match the Pi {SETTINGS_SCHEMA_VERSION} schema: "
                        f"{schema_error_summary(errors)}",
                        block=block,
                    )
                )
        return violations

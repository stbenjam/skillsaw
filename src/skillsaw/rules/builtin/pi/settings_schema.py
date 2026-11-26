"""Validate project .pi/settings.json against Pi's published settings schema."""

from functools import lru_cache
from itertools import chain
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


@lru_cache(maxsize=1)
def _legacy_skills_validator() -> "Draft202012Validator":
    """The schema's object branch for legacy ``skills``, under its own key.

    Validating the whole document reports a malformed legacy object only as
    an ``anyOf`` failure on ``skills``, which belongs to pi-config-valid.
    """
    from jsonschema import Draft202012Validator

    branches = settings_schema()["properties"]["skills"]["anyOf"]
    legacy = next(branch for branch in branches if branch.get("type") == "object")
    return Draft202012Validator({"properties": {"skills": legacy}})


class PiSettingsSchemaRule(Rule):
    """Check non-resource settings against the bundled Pi settings schema."""

    since = "0.23.0"
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
            # Streamed: the summary keeps a bounded sample and counts the rest.
            errors = (
                error
                for error in _validator().iter_errors(data)
                if not error.absolute_path or error.absolute_path[0] not in SETTINGS_RESOURCE_KEYS
            )
            skills = data.get("skills")
            if isinstance(skills, dict):
                # customDirectories is a resource list; the rest is ordinary settings.
                options = {k: v for k, v in skills.items() if k != "customDirectories"}
                errors = chain(errors, _legacy_skills_validator().iter_errors({"skills": options}))
            summary = schema_error_summary(errors)
            if summary:
                violations.append(
                    self.violation(
                        f"Pi settings do not match the Pi {SETTINGS_SCHEMA_VERSION} schema: "
                        f"{summary}",
                        block=block,
                    )
                )
        return violations

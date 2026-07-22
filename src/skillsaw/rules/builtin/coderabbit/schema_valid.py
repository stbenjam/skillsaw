"""
Rule for validating .coderabbit.yaml against the CodeRabbit configuration schema.

``coderabbit-yaml-valid`` only checks that the file parses as YAML. This rule
adds lightweight schema-conformance checks derived from CodeRabbit's published
JSON Schema (``schema.v2.json``): the top-level object is closed
(``additionalProperties: false``), so a misspelled top-level key (e.g. ``review``
instead of ``reviews``) is silently ignored by CodeRabbit and your configuration
partially reverts to defaults. We flag only *near-miss* unknown keys so that a
genuinely new upstream key never produces a false positive against skillsaw's
hand-copied snapshot.
"""

from __future__ import annotations

import difflib
from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.lint_target import CodeRabbitNode
from skillsaw.rules.builtin.utils import commented_key_line, read_yaml_commented

# Top-level keys defined by CodeRabbit's schema.v2.json (root object properties,
# which is `additionalProperties: false`). Hand-copied snapshot — re-verify
# against https://storage.googleapis.com/coderabbit_public_assets/schema.v2.json
# on each maintenance pass.
KNOWN_TOP_LEVEL_KEYS = (
    "language",
    "tone_instructions",
    "early_access",
    "enable_free_tier",
    "inheritance",
    "reviews",
    "chat",
    "knowledge_base",
    "code_generation",
    "issue_enrichment",
)

# Allowed values for `reviews.profile` (schema enum).
VALID_REVIEW_PROFILES = ("assertive", "chill", "quiet")


class CoderabbitSchemaValidRule(Rule):
    """Validate .coderabbit.yaml top-level keys and enums against the schema"""

    repo_types = {RepositoryType.CODERABBIT}

    since = "0.17.0"

    @property
    def rule_id(self) -> str:
        return "coderabbit-schema-valid"

    @property
    def description(self) -> str:
        return ".coderabbit.yaml keys and enums should match the CodeRabbit schema"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []

        cr_nodes = context.lint_tree.find(CodeRabbitNode)
        if not cr_nodes:
            return violations

        cr_path = cr_nodes[0].path

        # Well-formedness (parse errors, non-mapping) is coderabbit-yaml-valid's
        # job — stay silent here so we don't double-report.
        data, error, _ = read_yaml_commented(cr_path)
        if error or not isinstance(data, dict):
            return violations

        self._check_top_level_keys(data, cr_path, violations)
        self._check_review_profile(data, cr_path, violations)

        return violations

    def _check_top_level_keys(self, data, cr_path, violations) -> None:
        for key in data:
            if not isinstance(key, str) or key in KNOWN_TOP_LEVEL_KEYS:
                continue
            # CodeRabbit's schema is `additionalProperties: false`, but skillsaw
            # holds only a snapshot of the key set. Flag near-misses (likely
            # typos) and leave unfamiliar keys alone so a new upstream key never
            # false-positives.
            match = difflib.get_close_matches(key, KNOWN_TOP_LEVEL_KEYS, n=1, cutoff=0.8)
            if match:
                violations.append(
                    self.violation(
                        f"Unknown top-level key '{key}' (did you mean '{match[0]}'?). "
                        f"CodeRabbit ignores unrecognized top-level keys.",
                        file_path=cr_path,
                        line=commented_key_line(data, key),
                    )
                )

    def _check_review_profile(self, data, cr_path, violations) -> None:
        reviews = data.get("reviews")
        if not isinstance(reviews, dict):
            return
        if "profile" not in reviews:
            return
        profile = reviews["profile"]
        # The schema requires a string from a fixed enum, so any value outside
        # VALID_REVIEW_PROFILES — including lists, mappings, numbers, booleans,
        # and null — is invalid, not just misspelled strings.
        if profile not in VALID_REVIEW_PROFILES:
            violations.append(
                self.violation(
                    f"'reviews.profile' is '{profile}', expected one of: "
                    f"{', '.join(VALID_REVIEW_PROFILES)}",
                    file_path=cr_path,
                    line=commented_key_line(reviews, "profile"),
                )
            )

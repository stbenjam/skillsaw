"""Rule: mcp-registry-version-semver."""

from __future__ import annotations

from typing import List

from skillsaw.blocks import McpRegistryServerBlock
from skillsaw.context import RepositoryContext
from skillsaw.rule import Rule, RuleViolation, Severity

from ._helpers import (
    MCP_REGISTRY_REPO_TYPES,
    SEMVER,
    declares_unsupported_schema,
    is_release_source_placeholder,
    is_version_range,
)


class McpRegistryVersionSemverRule(Rule):
    """Recommend a strict Semantic Versioning 2.0.0 publisher version."""

    repo_types = MCP_REGISTRY_REPO_TYPES
    since = "0.20.0"
    target_dependencies = ("mcp-registry-server-json-valid",)

    @property
    def rule_id(self) -> str:
        return "mcp-registry-version-semver"

    @property
    def description(self) -> str:
        return "MCP Registry server versions should use strict Semantic Versioning 2.0.0"

    def default_severity(self) -> Severity:
        # Registry schema 2025-12-11 explicitly permits non-semantic
        # versions, so this cannot be a validity error.
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        for block in context.lint_tree.find(McpRegistryServerBlock):
            if (
                block.parse_error
                or block.raw_data is None
                or declares_unsupported_schema(block.raw_data)
            ):
                continue
            version = block.raw_data.get("version")
            if (
                isinstance(version, str)
                and not is_release_source_placeholder(version)
                and not is_version_range(version)
                and SEMVER.fullmatch(version) is None
            ):
                violations.append(
                    self.violation(
                        "'version' should use strict Semantic Versioning 2.0.0 "
                        "(for example, 1.2.3 or 1.2.3-beta.1+build.4)",
                        file_path=block.path,
                        fingerprint_discriminator="server:semver",
                    )
                )
        return violations

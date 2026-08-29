"""Rule: mcp-registry-server-json-valid."""

from __future__ import annotations

import re
from typing import List, Optional

from skillsaw.blocks import McpRegistryServerBlock
from skillsaw.context import RepositoryContext
from skillsaw.diagnostics import safe_display
from skillsaw.formats.mcp_registry import (
    MCP_REGISTRY_SCHEMA_ID,
    MCP_REGISTRY_SCHEMA_VERSION,
    mcp_registry_schema_version,
)
from skillsaw.rule import Rule, RuleViolation, Severity

from ._helpers import (
    MCP_REGISTRY_REPO_TYPES,
    is_version_range,
    registry_validator,
    schema_error_summary,
)

_DNS_LABEL = re.compile(r"\A[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\Z")
_SERVER_NAME = re.compile(r"\A[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?\Z")
_PACKAGE_TRANSPORTS = frozenset({"stdio", "streamable-http", "sse"})
_REMOTE_TRANSPORTS = frozenset({"streamable-http", "sse"})


def _name_problem(value: object) -> Optional[str]:
    """Return the reverse-DNS naming defect owned beyond the loose schema."""
    if not isinstance(value, str):
        return None
    if value.count("/") != 1:
        return "must contain exactly one '/' between its namespace and server name"
    namespace, server_name = value.split("/", 1)
    labels = namespace.split(".")
    if len(labels) < 2 or any(_DNS_LABEL.fullmatch(label) is None for label in labels):
        return "namespace must contain at least two valid reverse-DNS labels"
    if _SERVER_NAME.fullmatch(server_name) is None:
        return (
            "server name must use only ASCII letters, digits, dots, "
            "underscores, and hyphens, with a letter or digit at each end"
        )
    return None


def _schema_error_is_owned(
    error,
    *,
    invalid_name: bool,
    owned_errors: set[tuple[tuple, object]],
) -> bool:
    """Drop a schema error when a more precise semantic diagnostic owns it."""
    path = tuple(error.absolute_path)
    if invalid_name and path == ("name",) and error.validator == "pattern":
        return True
    return (path, error.validator) in owned_errors


class McpRegistryServerJsonValidRule(Rule):
    """Validate MCP Registry publisher metadata against schema and semantics."""

    repo_types = MCP_REGISTRY_REPO_TYPES
    since = "0.20.0"

    config_schema = {
        "registry-types": {
            "type": "list",
            "default": ["npm", "pypi", "cargo", "oci", "nuget", "mcpb"],
            "description": (
                "Package registryType values accepted in addition to the "
                "transport enums fixed by schema 2025-12-11"
            ),
        },
    }

    @property
    def rule_id(self) -> str:
        return "mcp-registry-server-json-valid"

    @property
    def description(self) -> str:
        return "MCP Registry server.json must conform to schema 2025-12-11 and its enums"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        allowed_setting = self.setting("registry-types")
        allowed_registry_types = frozenset(
            value
            for value in (allowed_setting if isinstance(allowed_setting, list) else [])
            if isinstance(value, str)
        )
        violations: List[RuleViolation] = []
        for block in context.lint_tree.find(McpRegistryServerBlock):
            violations.extend(self._check_block(block, allowed_registry_types))
        return violations

    def _check_block(
        self,
        block: McpRegistryServerBlock,
        allowed_registry_types: frozenset[str],
    ) -> List[RuleViolation]:
        if block.parse_error:
            return [
                self.violation(
                    f"Invalid JSON: {block.parse_error}",
                    file_path=block.path,
                    fingerprint_discriminator="server:json",
                )
            ]
        data = block.raw_data
        if data is None:
            return [
                self.violation(
                    "server.json must contain a JSON object",
                    file_path=block.path,
                    fingerprint_discriminator="server:not-object",
                )
            ]

        violations: List[RuleViolation] = []
        checked = dict(data)
        declared_schema = data.get("$schema")
        if declared_schema != MCP_REGISTRY_SCHEMA_ID:
            declared_version = mcp_registry_schema_version(declared_schema)
            if declared_version is not None:
                problem = (
                    f"Unsupported MCP Registry schema version "
                    f"'{safe_display(declared_version)}'; this skillsaw release "
                    f"supports {MCP_REGISTRY_SCHEMA_VERSION}"
                )
            elif "$schema" not in data:
                problem = f"Missing '$schema'; use {MCP_REGISTRY_SCHEMA_ID}"
            else:
                problem = (
                    "'$schema' must be the canonical MCP Registry "
                    f"{MCP_REGISTRY_SCHEMA_VERSION} identifier"
                )
            violations.append(
                self.violation(
                    problem,
                    file_path=block.path,
                    fingerprint_discriminator="server:schema-version",
                )
            )
            # The dedicated error above owns the identifier. Sanitizing this
            # view prevents a redundant URI-format schema error.
            checked["$schema"] = MCP_REGISTRY_SCHEMA_ID

        name_problem = _name_problem(data.get("name"))
        if name_problem:
            violations.append(
                self.violation(
                    f"'name' {name_problem}",
                    file_path=block.path,
                    fingerprint_discriminator="server:name",
                )
            )

        owned_schema_errors: set[tuple[tuple, object]] = set()
        version = data.get("version")
        if isinstance(version, str) and is_version_range(version):
            violations.append(
                self.violation(
                    "'version' must identify one exact release, not a tag or range",
                    file_path=block.path,
                    fingerprint_discriminator="server:version-range",
                )
            )

        packages = data.get("packages")
        if isinstance(packages, list):
            for index, package in enumerate(packages):
                if not isinstance(package, dict):
                    continue
                registry_type = package.get("registryType")
                if isinstance(registry_type, str) and registry_type not in allowed_registry_types:
                    violations.append(
                        self.violation(
                            f"packages[{index}].registryType must be one of "
                            f"{', '.join(sorted(allowed_registry_types))}",
                            file_path=block.path,
                            fingerprint_discriminator=f"package:{index}:registry-type",
                        )
                    )
                transport = package.get("transport")
                transport_type = transport.get("type") if isinstance(transport, dict) else None
                if isinstance(transport_type, str) and transport_type not in _PACKAGE_TRANSPORTS:
                    owned_schema_errors.add((("packages", index, "transport"), "anyOf"))
                    violations.append(
                        self.violation(
                            f"packages[{index}].transport.type must be one of "
                            "sse, stdio, streamable-http",
                            file_path=block.path,
                            fingerprint_discriminator=f"package:{index}:transport",
                        )
                    )
                package_version = package.get("version")
                if isinstance(package_version, str) and is_version_range(package_version):
                    if package_version == "latest":
                        owned_schema_errors.add((("packages", index, "version"), "not"))
                    violations.append(
                        self.violation(
                            f"packages[{index}].version must identify one exact "
                            "release, not a tag or range",
                            file_path=block.path,
                            fingerprint_discriminator=f"package:{index}:version-range",
                        )
                    )

        remotes = data.get("remotes")
        if isinstance(remotes, list):
            for index, remote in enumerate(remotes):
                if not isinstance(remote, dict):
                    continue
                transport_type = remote.get("type")
                if isinstance(transport_type, str) and transport_type not in _REMOTE_TRANSPORTS:
                    owned_schema_errors.add((("remotes", index), "anyOf"))
                    violations.append(
                        self.violation(
                            f"remotes[{index}].type must be one of sse, streamable-http",
                            file_path=block.path,
                            fingerprint_discriminator=f"remote:{index}:transport",
                        )
                    )

        schema_summary = schema_error_summary(
            error
            for error in registry_validator().iter_errors(checked)
            if not _schema_error_is_owned(
                error,
                invalid_name=name_problem is not None,
                owned_errors=owned_schema_errors,
            )
        )
        if schema_summary:
            violations.append(
                self.violation(
                    f"server.json does not conform to MCP Registry "
                    f"{MCP_REGISTRY_SCHEMA_VERSION}: {schema_summary}",
                    file_path=block.path,
                    fingerprint_discriminator="server:schema",
                )
            )
        return violations

"""Rule: mcp-registry-server-json-valid."""

from __future__ import annotations

import re
from typing import List, Optional
from urllib.parse import urlsplit

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
    SEMVER,
    is_version_range,
    registry_validator,
    schema_error_summary,
)

_DNS_LABEL = re.compile(r"\A[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\Z")
_SERVER_NAME = re.compile(r"\A[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?\Z")
_CLEAN_SUBFOLDER = re.compile(r"\A[A-Za-z0-9._/-]+\Z")
_PACKAGE_TRANSPORTS = frozenset({"stdio", "streamable-http", "sse"})
_REMOTE_TRANSPORTS = frozenset({"streamable-http", "sse"})
_SEMANTIC_SAMPLE_LIMIT = 4


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


def _is_clean_relative_subfolder(value: str) -> bool:
    """Match the Registry's filesystem-free subfolder shape validation."""
    if not value:
        return True
    if value.startswith("/") or value.endswith("/") or _CLEAN_SUBFOLDER.fullmatch(value) is None:
        return False
    return all(segment not in {"", ".", ".."} for segment in value.split("/"))


def _is_https_url(value: str) -> bool:
    """Require the network authority implied by the schema's HTTPS URL contract."""
    try:
        parsed = urlsplit(value)
        return parsed.scheme.lower() == "https" and parsed.hostname is not None
    except ValueError:
        return False


def _mapping_item(data: dict, key: str, index: object) -> Optional[dict]:
    """Return one mapping-valued list item from untrusted publisher data."""
    values = data.get(key)
    if not isinstance(index, int) or not isinstance(values, list):
        return None
    if index < 0 or index >= len(values):
        return None
    value = values[index]
    return value if isinstance(value, dict) else None


def _schema_error_is_owned(error, *, invalid_name: bool, data: dict) -> bool:
    """Drop a schema error when a more precise semantic diagnostic owns it."""
    path = tuple(error.absolute_path)
    if invalid_name and path == ("name",) and error.validator == "pattern":
        return True
    if len(path) == 3 and path[0] == "packages":
        package = _mapping_item(data, "packages", path[1])
        if package is None:
            return False
        if path[2] == "transport" and error.validator == "anyOf":
            transport = package.get("transport")
            transport_type = transport.get("type") if isinstance(transport, dict) else None
            return isinstance(transport_type, str) and transport_type not in _PACKAGE_TRANSPORTS
        if path[2] == "version" and error.validator == "not":
            package_version = package.get("version")
            return isinstance(package_version, str) and is_version_range(package_version)
    if len(path) == 2 and path[0] == "remotes" and error.validator == "anyOf":
        remote = _mapping_item(data, "remotes", path[1])
        remote_type = remote.get("type") if remote is not None else None
        return isinstance(remote_type, str) and remote_type not in _REMOTE_TRANSPORTS
    return False


def _indexed_problem(
    collection: str,
    field: str,
    indices: list[int],
    count: int,
    requirement: str,
) -> str:
    """Render one bounded diagnostic for a repeated indexed defect."""
    if count == 1:
        subject = f"{collection}[{indices[0]}]{field}"
    else:
        shown = ", ".join(str(index) for index in indices)
        remaining = count - len(indices)
        if remaining:
            shown += f", and {remaining} more"
        subject = f"{collection}[]{field} at indices {shown}"
    return f"{subject} {requirement}"


def _registry_types_summary(values: frozenset[str], *, limit: int = 20) -> str:
    """Render configured values safely without allowing an unbounded message."""
    ordered = sorted(values)
    rendered = ", ".join(safe_display(value) for value in ordered[:limit])
    remaining = len(ordered) - limit
    if remaining > 0:
        rendered += f", and {remaining} more"
    return rendered or "(none configured)"


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

        version = data.get("version")
        if isinstance(version, str) and is_version_range(version):
            violations.append(
                self.violation(
                    "'version' must identify one exact release, not a tag or range",
                    file_path=block.path,
                    fingerprint_discriminator="server:version-range",
                )
            )

        semantic_counts = {
            "registry-type": 0,
            "package-transport": 0,
            "package-version": 0,
            "mcpb-hash": 0,
            "remote-transport": 0,
            "icon-src": 0,
        }
        semantic_indices = {key: [] for key in semantic_counts}

        def record_semantic(kind: str, index: int) -> None:
            semantic_counts[kind] += 1
            if len(semantic_indices[kind]) < _SEMANTIC_SAMPLE_LIMIT:
                semantic_indices[kind].append(index)

        packages = data.get("packages")
        if isinstance(packages, list):
            for index, package in enumerate(packages):
                if not isinstance(package, dict):
                    continue
                registry_type = package.get("registryType")
                if isinstance(registry_type, str) and registry_type not in allowed_registry_types:
                    record_semantic("registry-type", index)
                transport = package.get("transport")
                transport_type = transport.get("type") if isinstance(transport, dict) else None
                if isinstance(transport_type, str) and transport_type not in _PACKAGE_TRANSPORTS:
                    record_semantic("package-transport", index)
                package_version = package.get("version")
                if isinstance(package_version, str) and (
                    is_version_range(package_version)
                    or (registry_type == "npm" and SEMVER.fullmatch(package_version) is None)
                ):
                    record_semantic("package-version", index)
                if registry_type == "mcpb" and "fileSha256" not in package:
                    record_semantic("mcpb-hash", index)

        remotes = data.get("remotes")
        if isinstance(remotes, list):
            for index, remote in enumerate(remotes):
                if not isinstance(remote, dict):
                    continue
                transport_type = remote.get("type")
                if isinstance(transport_type, str) and transport_type not in _REMOTE_TRANSPORTS:
                    record_semantic("remote-transport", index)

        icons = data.get("icons")
        if isinstance(icons, list):
            for index, icon in enumerate(icons):
                src = icon.get("src") if isinstance(icon, dict) else None
                if isinstance(src, str) and not _is_https_url(src):
                    record_semantic("icon-src", index)

        repository = data.get("repository")
        subfolder = repository.get("subfolder") if isinstance(repository, dict) else None
        if isinstance(subfolder, str) and not _is_clean_relative_subfolder(subfolder):
            violations.append(
                self.violation(
                    "repository.subfolder must be a clean relative path",
                    file_path=block.path,
                    fingerprint_discriminator="semantic:repository-subfolder",
                )
            )

        semantic_specs = (
            (
                "registry-type",
                "packages",
                ".registryType",
                f"must be one of {_registry_types_summary(allowed_registry_types)}",
            ),
            (
                "package-transport",
                "packages",
                ".transport.type",
                "must be one of sse, stdio, streamable-http",
            ),
            (
                "package-version",
                "packages",
                ".version",
                "must identify one exact release, not a tag or range",
            ),
            (
                "mcpb-hash",
                "packages",
                ".fileSha256",
                "is required when registryType is mcpb",
            ),
            (
                "remote-transport",
                "remotes",
                ".type",
                "must be one of sse, streamable-http",
            ),
            (
                "icon-src",
                "icons",
                ".src",
                "must use an HTTPS URI",
            ),
        )
        for kind, collection, field, requirement in semantic_specs:
            count = semantic_counts[kind]
            if count:
                violations.append(
                    self.violation(
                        _indexed_problem(
                            collection,
                            field,
                            semantic_indices[kind],
                            count,
                            requirement,
                        ),
                        file_path=block.path,
                        fingerprint_discriminator=f"semantic:{kind}",
                    )
                )

        schema_summary = schema_error_summary(
            error
            for error in registry_validator().iter_errors(checked)
            if not _schema_error_is_owned(
                error,
                invalid_name=name_problem is not None,
                data=data,
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

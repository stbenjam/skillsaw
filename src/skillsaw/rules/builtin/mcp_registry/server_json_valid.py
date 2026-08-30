"""Rule: mcp-registry-server-json-valid."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import List, Mapping, Optional
from urllib.parse import urlsplit

from skillsaw.blocks import McpRegistryServerBlock
from skillsaw.context import RepositoryContext
from skillsaw.diagnostics import safe_display
from skillsaw.formats.mcp_registry import (
    MCP_REGISTRY_SCHEMA_ID,
    MCP_REGISTRY_SCHEMA_PROFILES,
    MCP_REGISTRY_SCHEMA_VERSION,
    MCP_REGISTRY_SCHEMA_VERSIONS,
    McpRegistrySchemaProfile,
    mcp_registry_schema_version,
)
from skillsaw.rule import Rule, RuleViolation, Severity

from ._helpers import (
    MCP_REGISTRY_REPO_TYPES,
    SEMVER,
    analyze_http_url_template,
    is_clean_repository_subfolder,
    is_loopback_hostname,
    is_package_version_range,
    is_release_source_placeholder,
    is_uri,
    is_version_range,
    registry_validator,
    schema_error_summary,
)

_DNS_LABEL = re.compile(r"\A[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\Z")
_SERVER_NAME = re.compile(r"\A[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?\Z")
_SEMANTIC_SAMPLE_LIMIT = 4
_VERSIONED_PACKAGE_REGISTRIES = frozenset({"npm", "pypi", "cargo", "nuget"})
_COMPATIBLE_REGISTRY_BASE_URLS: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "npm": frozenset({"https://registry.npmjs.org"}),
        "pypi": frozenset({"https://pypi.org"}),
        "nuget": frozenset({"https://api.nuget.org", "https://api.nuget.org/v3/index.json"}),
    }
)
_CURRENT_REGISTRY_BASE_URLS: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "npm": frozenset({"https://registry.npmjs.org"}),
        "pypi": frozenset({"https://pypi.org"}),
        "nuget": frozenset({"https://api.nuget.org/v3/index.json"}),
        "cargo": frozenset({"https://crates.io"}),
    }
)
_NO_REGISTRY_BASE_URLS: Mapping[str, frozenset[str]] = MappingProxyType({})
_FORBIDDEN_REGISTRY_BASE_URLS = frozenset({"oci", "mcpb"})
_FORBIDDEN_FILE_HASHES = frozenset({"npm", "pypi", "nuget", "oci"})
_CURRENT_FORBIDDEN_FILE_HASHES = _FORBIDDEN_FILE_HASHES | {"cargo"}
_PLACEHOLDER_IDENTIFIERS: Mapping[str, str] = MappingProxyType(
    {
        "npm": "@example/server",
        "pypi": "example-server",
        "cargo": "example-server",
        "nuget": "Example.Server",
        "oci": "docker.io/example/server:1.0.0",
        "mcpb": "https://example.com/server.mcpb",
    }
)
_REPOSITORY_URLS: Mapping[str, re.Pattern] = MappingProxyType(
    {
        source: re.compile(
            rf"\Ahttps?://(?:www\.)?{source}\.com/" r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/?\Z"
        )
        for source in ("github", "gitlab")
    }
)


@dataclass(frozen=True)
class _SemanticPolicy:
    """Semantic checks paired with one or more immutable schema versions."""

    package_transports: frozenset[str]
    remote_transports: frozenset[str]
    registry_types: frozenset[str]
    required_package_versions: frozenset[str] = frozenset()
    forbidden_package_versions: frozenset[str] = frozenset()
    publisher_status_allowed: bool = False
    official_metadata_allowed: bool = False
    reverse_dns_name: bool = True
    exact_versions: bool = True
    http_url_templates: bool = True
    mcpb_hash: bool = True
    https_icons: bool = True
    clean_repository_subfolder: bool = True
    canonical_registry_base_urls: Mapping[str, frozenset[str]] = field(
        default_factory=lambda: _NO_REGISTRY_BASE_URLS
    )
    forbidden_registry_base_urls: frozenset[str] = frozenset()
    forbidden_file_hashes: frozenset[str] = frozenset()
    mcpb_identifier_constraints: bool = True


def _semantic_policy(
    *,
    https_icons: bool,
    publisher_managed_fields: bool = False,
    required_package_versions: frozenset[str] = frozenset(),
    forbidden_package_versions: frozenset[str] = frozenset(),
    canonical_registry_base_urls: Mapping[str, frozenset[str]] = _COMPATIBLE_REGISTRY_BASE_URLS,
    forbidden_registry_base_urls: frozenset[str] = frozenset(),
    forbidden_file_hashes: frozenset[str] = frozenset(),
) -> _SemanticPolicy:
    """Build the common publisher policy with version-gated features."""
    return _SemanticPolicy(
        package_transports=frozenset({"stdio", "streamable-http", "sse"}),
        remote_transports=frozenset({"streamable-http", "sse"}),
        registry_types=frozenset({"npm", "pypi", "cargo", "oci", "nuget", "mcpb"}),
        required_package_versions=required_package_versions,
        forbidden_package_versions=forbidden_package_versions,
        canonical_registry_base_urls=canonical_registry_base_urls,
        forbidden_registry_base_urls=forbidden_registry_base_urls,
        forbidden_file_hashes=forbidden_file_hashes,
        publisher_status_allowed=publisher_managed_fields,
        official_metadata_allowed=publisher_managed_fields,
        https_icons=https_icons,
    )


_SEMANTIC_POLICIES: Mapping[str, _SemanticPolicy] = MappingProxyType(
    {
        "2025-07-09": _semantic_policy(
            https_icons=False,
            publisher_managed_fields=True,
        ),
        "2025-09-16": _semantic_policy(
            https_icons=False,
            publisher_managed_fields=True,
        ),
        "2025-09-29": _semantic_policy(https_icons=False),
        "2025-10-11": _semantic_policy(
            https_icons=True,
            required_package_versions=_VERSIONED_PACKAGE_REGISTRIES,
            forbidden_package_versions=frozenset({"mcpb", "oci"}),
            forbidden_registry_base_urls=_FORBIDDEN_REGISTRY_BASE_URLS,
            forbidden_file_hashes=_FORBIDDEN_FILE_HASHES,
        ),
        "2025-10-17": _semantic_policy(
            https_icons=True,
            required_package_versions=_VERSIONED_PACKAGE_REGISTRIES,
            forbidden_package_versions=frozenset({"oci"}),
            forbidden_registry_base_urls=_FORBIDDEN_REGISTRY_BASE_URLS,
            forbidden_file_hashes=_FORBIDDEN_FILE_HASHES,
        ),
        "2025-12-11": _semantic_policy(
            https_icons=True,
            required_package_versions=_VERSIONED_PACKAGE_REGISTRIES,
            forbidden_package_versions=frozenset({"oci"}),
            canonical_registry_base_urls=_CURRENT_REGISTRY_BASE_URLS,
            forbidden_registry_base_urls=_FORBIDDEN_REGISTRY_BASE_URLS,
            forbidden_file_hashes=_CURRENT_FORBIDDEN_FILE_HASHES,
        ),
    }
)


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


def _schema_checked_document(
    data: dict,
    schema_profile: McpRegistrySchemaProfile,
) -> dict:
    """Substitute exact release placeholders only in the schema-validation view."""
    checked = dict(data)
    if is_release_source_placeholder(checked.get("name")):
        checked["name"] = "io.github.example/server"
    if is_release_source_placeholder(checked.get("version")):
        checked["version"] = "1.0.0"

    packages = checked.get("packages")
    if not isinstance(packages, list):
        return checked

    checked_packages = list(packages)
    changed = False
    for index, package in enumerate(packages):
        if not isinstance(package, dict):
            continue
        raw_registry_type = package.get(schema_profile.registry_type_field)
        registry_type = raw_registry_type if isinstance(raw_registry_type, str) else None
        substitutions = {}
        if is_release_source_placeholder(package.get("identifier")):
            substitutions["identifier"] = _PLACEHOLDER_IDENTIFIERS.get(
                registry_type, "example-server"
            )
        if is_release_source_placeholder(package.get("version")):
            substitutions["version"] = "1.0.0"
        if is_release_source_placeholder(package.get(schema_profile.file_sha256_field)):
            substitutions[schema_profile.file_sha256_field] = "0" * 64
        if substitutions:
            checked_packages[index] = {**package, **substitutions}
            changed = True
    if changed:
        checked["packages"] = checked_packages
    return checked


def _package_template_variables(
    package: dict,
    schema_profile: McpRegistrySchemaProfile,
) -> frozenset[str]:
    """Collect URL variables from the package fields the publisher resolves."""
    variables = set()
    environment = package.get(schema_profile.environment_variables_field)
    if isinstance(environment, list):
        for item in environment:
            name = item.get("name") if isinstance(item, dict) else None
            if isinstance(name, str) and name:
                variables.add(name)
    for field in (
        schema_profile.runtime_arguments_field,
        schema_profile.package_arguments_field,
    ):
        arguments = package.get(field)
        if not isinstance(arguments, list):
            continue
        for argument in arguments:
            if not isinstance(argument, dict):
                continue
            for key in ("name", schema_profile.value_hint_field):
                value = argument.get(key)
                if isinstance(value, str) and value:
                    variables.add(value)
    return frozenset(variables)


def _remote_template_variables(remote: dict) -> frozenset[str]:
    """Collect URL variables from the current remote extension vocabulary."""
    variables = remote.get("variables")
    if not isinstance(variables, dict):
        return frozenset()
    return frozenset(key for key in variables if isinstance(key, str) and key)


def _repository_url_is_official_shape(repository: object) -> bool:
    """Whether source and URL use the publisher's supported forge shape."""
    if not isinstance(repository, dict):
        return True
    source = repository.get("source")
    url = repository.get("url")
    if not isinstance(source, str) or not isinstance(url, str) or not is_uri(url):
        return True
    pattern = _REPOSITORY_URLS.get(source)
    return pattern is not None and pattern.fullmatch(url) is not None


def _schema_error_is_owned(
    error,
    *,
    invalid_name: bool,
    data: dict,
    semantic_policy: _SemanticPolicy,
) -> bool:
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
            return (
                isinstance(transport_type, str)
                and transport_type not in semantic_policy.package_transports
            )
        if semantic_policy.exact_versions and path[2] == "version" and error.validator == "not":
            package_version = package.get("version")
            return isinstance(package_version, str) and is_version_range(package_version)
    if len(path) == 2 and path[0] == "remotes" and error.validator == "anyOf":
        remote = _mapping_item(data, "remotes", path[1])
        remote_type = remote.get("type") if remote is not None else None
        return isinstance(remote_type, str) and remote_type not in semantic_policy.remote_transports
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


@dataclass(frozen=True)
class _SemanticSpec:
    """One ordered, aggregated semantic diagnostic."""

    kind: str
    collection: str
    field: str
    requirement: str


@dataclass
class _SemanticState:
    """Bounded matches for one semantic diagnostic."""

    spec: _SemanticSpec
    count: int = 0
    indices: list[int] = field(default_factory=list)


class _IndexedSemanticFindings:
    """Collect and render indexed findings without duplicating their vocabulary."""

    def __init__(self, specs: tuple[_SemanticSpec, ...]) -> None:
        self._ordered_states = tuple(_SemanticState(spec) for spec in specs)
        self._states = {state.spec.kind: state for state in self._ordered_states}
        if len(self._states) != len(self._ordered_states):
            raise ValueError("duplicate MCP Registry semantic finding kind")

    def record(self, kind: str, index: int) -> None:
        state = self._states[kind]
        state.count += 1
        if len(state.indices) < _SEMANTIC_SAMPLE_LIMIT:
            state.indices.append(index)

    def problems(self) -> list[tuple[str, str]]:
        """Return ``(fingerprint, message)`` pairs in declaration order."""
        problems = []
        for state in self._ordered_states:
            if not state.count:
                continue
            spec = state.spec
            problems.append(
                (
                    f"semantic:{spec.kind}",
                    _indexed_problem(
                        spec.collection,
                        spec.field,
                        state.indices,
                        state.count,
                        spec.requirement,
                    ),
                )
            )
        return problems


def _semantic_specs(
    schema_profile: McpRegistrySchemaProfile,
    semantic_policy: _SemanticPolicy,
    allowed_registry_types: frozenset[str],
) -> tuple[_SemanticSpec, ...]:
    """Declare the complete ordered vocabulary of indexed findings once."""
    return (
        _SemanticSpec(
            "registry-type",
            "packages",
            f".{schema_profile.registry_type_field}",
            f"must be one of {_registry_types_summary(allowed_registry_types)}",
        ),
        _SemanticSpec(
            "package-transport",
            "packages",
            ".transport.type",
            f"must be one of {', '.join(sorted(semantic_policy.package_transports))}",
        ),
        _SemanticSpec(
            "package-url",
            "packages",
            ".transport.url",
            "must be a structurally valid HTTP(S) URL template",
        ),
        _SemanticSpec(
            "package-stdio-url",
            "packages",
            ".transport.url",
            "must be empty or omitted for stdio transport",
        ),
        _SemanticSpec(
            "package-url-variable",
            "packages",
            ".transport.url",
            "must reference only declared package arguments or environment variables",
        ),
        _SemanticSpec(
            "registry-base-url",
            "packages",
            f".{schema_profile.registry_base_url_field}",
            "must be the canonical public base URL for its registry type",
        ),
        _SemanticSpec(
            "registry-base-url-forbidden",
            "packages",
            f".{schema_profile.registry_base_url_field}",
            "must be omitted for OCI and MCPB packages",
        ),
        _SemanticSpec(
            "file-hash-forbidden",
            "packages",
            f".{schema_profile.file_sha256_field}",
            "must be omitted unless the package is MCPB",
        ),
        _SemanticSpec(
            "mcpb-identifier",
            "packages",
            ".identifier",
            "must be an HTTPS URL containing 'mcp' for MCPB packages",
        ),
        _SemanticSpec(
            "package-version",
            "packages",
            ".version",
            "must identify one exact release, not a tag or range",
        ),
        _SemanticSpec(
            "package-version-forbidden",
            "packages",
            ".version",
            "must be omitted when "
            f"{schema_profile.registry_type_field} is one of "
            f"{', '.join(sorted(semantic_policy.forbidden_package_versions))}",
        ),
        _SemanticSpec(
            "mcpb-hash",
            "packages",
            f".{schema_profile.file_sha256_field}",
            f"is required when {schema_profile.registry_type_field} is mcpb",
        ),
        _SemanticSpec(
            "remote-transport",
            "remotes",
            ".type",
            f"must be one of {', '.join(sorted(semantic_policy.remote_transports))}",
        ),
        _SemanticSpec(
            "remote-url",
            "remotes",
            ".url",
            "must be a structurally valid HTTPS URL template using a non-loopback host",
        ),
        _SemanticSpec(
            "remote-url-variable",
            "remotes",
            ".url",
            "must reference only keys declared in the remote variables object",
        ),
        _SemanticSpec("icon-src", "icons", ".src", "must use an HTTPS URI"),
    )


def _collect_package_semantics(
    packages: object,
    schema_profile: McpRegistrySchemaProfile,
    semantic_policy: _SemanticPolicy,
    allowed_registry_types: frozenset[str],
    findings: _IndexedSemanticFindings,
) -> None:
    """Collect package defects in one linear pass."""
    if not isinstance(packages, list):
        return
    for index, package in enumerate(packages):
        if not isinstance(package, dict):
            continue
        raw_registry_type = package.get(schema_profile.registry_type_field)
        registry_type = raw_registry_type if isinstance(raw_registry_type, str) else None
        if registry_type is not None and registry_type not in allowed_registry_types:
            findings.record("registry-type", index)
        transport = package.get("transport")
        raw_transport_type = transport.get("type") if isinstance(transport, dict) else None
        transport_type = raw_transport_type if isinstance(raw_transport_type, str) else None
        if transport_type is not None and transport_type not in semantic_policy.package_transports:
            findings.record("package-transport", index)
        transport_url = transport.get("url") if isinstance(transport, dict) else None
        if (
            transport_type == "stdio"
            and isinstance(transport, dict)
            and "url" in transport
            and transport_url is not None
            and transport_url != ""
        ):
            findings.record("package-stdio-url", index)
        package_url = (
            analyze_http_url_template(transport_url) if isinstance(transport_url, str) else None
        )
        if (
            semantic_policy.http_url_templates
            and transport_type in semantic_policy.remote_transports
            and isinstance(transport_url, str)
            and package_url is None
        ):
            findings.record("package-url", index)
        if (
            semantic_policy.http_url_templates
            and transport_type in semantic_policy.remote_transports
            and package_url is not None
            and not package_url.variables <= _package_template_variables(package, schema_profile)
        ):
            findings.record("package-url-variable", index)
        registry_base_url = package.get(schema_profile.registry_base_url_field)
        canonical_base_urls = semantic_policy.canonical_registry_base_urls.get(registry_type)
        if (
            isinstance(registry_base_url, str)
            and registry_base_url
            and canonical_base_urls is not None
            and registry_base_url not in canonical_base_urls
        ):
            findings.record("registry-base-url", index)
        if (
            isinstance(registry_base_url, str)
            and registry_base_url
            and registry_type in semantic_policy.forbidden_registry_base_urls
        ):
            findings.record("registry-base-url-forbidden", index)
        file_hash = package.get(schema_profile.file_sha256_field)
        if (
            isinstance(file_hash, str)
            and file_hash
            and registry_type in semantic_policy.forbidden_file_hashes
        ):
            findings.record("file-hash-forbidden", index)
        identifier = package.get("identifier")
        if (
            semantic_policy.mcpb_identifier_constraints
            and registry_type == "mcpb"
            and isinstance(identifier, str)
            and not is_release_source_placeholder(identifier)
            and (not _is_https_url(identifier) or "mcp" not in identifier.lower())
        ):
            findings.record("mcpb-identifier", index)
        package_version = package.get("version")
        if semantic_policy.exact_versions and (
            (
                registry_type in semantic_policy.required_package_versions
                and "version" not in package
            )
            or (
                isinstance(package_version, str)
                and not is_release_source_placeholder(package_version)
                and registry_type not in semantic_policy.forbidden_package_versions
                and (
                    is_package_version_range(registry_type, package_version)
                    or (registry_type == "npm" and SEMVER.fullmatch(package_version) is None)
                )
            )
        ):
            findings.record("package-version", index)
        if registry_type in semantic_policy.forbidden_package_versions and isinstance(
            package_version, str
        ):
            findings.record("package-version-forbidden", index)
        if (
            semantic_policy.mcpb_hash
            and registry_type == "mcpb"
            and schema_profile.file_sha256_field not in package
        ):
            findings.record("mcpb-hash", index)


def _collect_remote_semantics(
    remotes: object,
    semantic_policy: _SemanticPolicy,
    findings: _IndexedSemanticFindings,
) -> None:
    """Collect remote defects in one linear pass."""
    if not isinstance(remotes, list):
        return
    for index, remote in enumerate(remotes):
        if not isinstance(remote, dict):
            continue
        transport_type = remote.get("type")
        if (
            isinstance(transport_type, str)
            and transport_type not in semantic_policy.remote_transports
        ):
            findings.record("remote-transport", index)
        remote_url = remote.get("url")
        analyzed_remote_url = (
            analyze_http_url_template(remote_url) if isinstance(remote_url, str) else None
        )
        if (
            semantic_policy.http_url_templates
            and isinstance(remote_url, str)
            and (
                analyzed_remote_url is None
                or analyzed_remote_url.scheme != "https"
                or is_loopback_hostname(analyzed_remote_url.hostname)
            )
        ):
            findings.record("remote-url", index)
        if (
            semantic_policy.http_url_templates
            and analyzed_remote_url is not None
            and not analyzed_remote_url.variables <= _remote_template_variables(remote)
        ):
            findings.record("remote-url-variable", index)


def _collect_icon_semantics(
    icons: object,
    semantic_policy: _SemanticPolicy,
    findings: _IndexedSemanticFindings,
) -> None:
    """Collect icon defects in one linear pass."""
    if not isinstance(icons, list):
        return
    for index, icon in enumerate(icons):
        src = icon.get("src") if isinstance(icon, dict) else None
        if semantic_policy.https_icons and isinstance(src, str) and not _is_https_url(src):
            findings.record("icon-src", index)


class McpRegistryServerJsonValidRule(Rule):
    """Validate MCP Registry publisher metadata against schema and semantics."""

    repo_types = MCP_REGISTRY_REPO_TYPES
    since = "0.20.0"

    config_schema = {
        "registry-types": {
            "type": "list",
            "default": [],
            "description": (
                "Additional package registryType values accepted alongside "
                "the vocabulary fixed by the document's schema version"
            ),
        },
    }

    @property
    def rule_id(self) -> str:
        return "mcp-registry-server-json-valid"

    @property
    def description(self) -> str:
        return "MCP Registry server.json must conform to a supported schema and its enums"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        allowed_setting = self.setting("registry-types")
        additional_registry_types = frozenset(
            value
            for value in (allowed_setting if isinstance(allowed_setting, list) else [])
            if isinstance(value, str)
        )
        violations: List[RuleViolation] = []
        for block in self.dependency_scoped_find(context, McpRegistryServerBlock):
            violations.extend(self._check_block(block, additional_registry_types))
        return violations

    def _check_block(
        self,
        block: McpRegistryServerBlock,
        additional_registry_types: frozenset[str],
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
        declared_version = mcp_registry_schema_version(declared_schema)
        schema_version = MCP_REGISTRY_SCHEMA_VERSION
        if declared_version is not None:
            if declared_version not in MCP_REGISTRY_SCHEMA_VERSIONS:
                supported = ", ".join(sorted(MCP_REGISTRY_SCHEMA_VERSIONS))
                return [
                    self.violation(
                        f"Unsupported MCP Registry schema version "
                        f"'{safe_display(declared_version)}'; this skillsaw release "
                        f"supports {supported}",
                        file_path=block.path,
                        fingerprint_discriminator="server:schema-version",
                    )
                ]
            schema_version = declared_version
        elif declared_schema != MCP_REGISTRY_SCHEMA_ID:
            if "$schema" not in data:
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

        semantic_policy = _SEMANTIC_POLICIES[schema_version]
        schema_profile = MCP_REGISTRY_SCHEMA_PROFILES[schema_version]
        checked = _schema_checked_document(checked, schema_profile)
        allowed_registry_types = semantic_policy.registry_types | additional_registry_types

        name = data.get("name")
        name_problem = (
            _name_problem(name)
            if semantic_policy.reverse_dns_name and not is_release_source_placeholder(name)
            else None
        )
        if name_problem:
            violations.append(
                self.violation(
                    f"'name' {name_problem}",
                    file_path=block.path,
                    fingerprint_discriminator="server:name",
                )
            )

        if not semantic_policy.publisher_status_allowed and "status" in data:
            violations.append(
                self.violation(
                    f"'status' is Registry-managed in schema {schema_version} "
                    "and must not appear in publisher metadata",
                    file_path=block.path,
                    fingerprint_discriminator="semantic:publisher-status",
                )
            )

        metadata = data.get("_meta")
        official_metadata_key = "io.modelcontextprotocol.registry/official"
        if (
            not semantic_policy.official_metadata_allowed
            and isinstance(metadata, dict)
            and official_metadata_key in metadata
        ):
            violations.append(
                self.violation(
                    f"'_meta.{official_metadata_key}' is Registry-managed in "
                    f"schema {schema_version} and must not appear in publisher metadata",
                    file_path=block.path,
                    fingerprint_discriminator="semantic:official-metadata",
                )
            )

        version = data.get("version")
        if (
            semantic_policy.exact_versions
            and isinstance(version, str)
            and not is_release_source_placeholder(version)
            and is_version_range(version)
        ):
            violations.append(
                self.violation(
                    "'version' must identify one exact release, not a tag or range",
                    file_path=block.path,
                    fingerprint_discriminator="server:version-range",
                )
            )

        indexed_findings = _IndexedSemanticFindings(
            _semantic_specs(schema_profile, semantic_policy, allowed_registry_types)
        )
        _collect_package_semantics(
            data.get("packages"),
            schema_profile,
            semantic_policy,
            allowed_registry_types,
            indexed_findings,
        )
        _collect_remote_semantics(data.get("remotes"), semantic_policy, indexed_findings)
        _collect_icon_semantics(data.get("icons"), semantic_policy, indexed_findings)

        repository = data.get("repository")
        if not _repository_url_is_official_shape(repository):
            violations.append(
                self.violation(
                    "repository.url must match its supported github or gitlab source",
                    file_path=block.path,
                    fingerprint_discriminator="semantic:repository-url",
                )
            )
        subfolder = repository.get("subfolder") if isinstance(repository, dict) else None
        if (
            semantic_policy.clean_repository_subfolder
            and isinstance(subfolder, str)
            and not is_clean_repository_subfolder(subfolder)
        ):
            violations.append(
                self.violation(
                    "repository.subfolder must be a clean relative path",
                    file_path=block.path,
                    fingerprint_discriminator="semantic:repository-subfolder",
                )
            )

        for fingerprint, problem in indexed_findings.problems():
            violations.append(
                self.violation(
                    problem,
                    file_path=block.path,
                    fingerprint_discriminator=fingerprint,
                )
            )

        schema_summary = schema_error_summary(
            error
            for error in registry_validator(schema_version).iter_errors(checked)
            if not _schema_error_is_owned(
                error,
                invalid_name=name_problem is not None,
                data=data,
                semantic_policy=semantic_policy,
            )
        )
        if schema_summary:
            violations.append(
                self.violation(
                    f"server.json does not conform to MCP Registry "
                    f"{schema_version}: {schema_summary}",
                    file_path=block.path,
                    fingerprint_discriminator="server:schema",
                )
            )
        return violations

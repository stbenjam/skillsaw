"""Rule: mcp-registry-npm-name-match."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlsplit

from skillsaw.blocks import McpRegistryNpmPackageBlock, McpRegistryServerBlock
from skillsaw.context import RepositoryContext
from skillsaw.diagnostics import safe_display
from skillsaw.formats.mcp_registry import (
    MCP_REGISTRY_SCHEMA_PROFILES,
    MCP_REGISTRY_SCHEMA_VERSION,
    mcp_registry_schema_version,
)
from skillsaw.paths import safe_resolve
from skillsaw.rule import Rule, RuleViolation, Severity

from ._helpers import (
    MCP_REGISTRY_REPO_TYPES,
    declares_unsupported_schema,
    is_clean_repository_subfolder,
    stable_key,
)


@dataclass(frozen=True)
class _NpmReference:
    """One npm coordinate declared by one Registry publisher document."""

    server: McpRegistryServerBlock
    server_name: str
    identifier: str
    version: str


class _PackageCandidates:
    """Path-first package lookup with a lazy coordinate fallback index."""

    def __init__(self, manifests: List[McpRegistryNpmPackageBlock]):
        self.by_path: Dict[Path, McpRegistryNpmPackageBlock] = {}
        for manifest in manifests:
            resolved = safe_resolve(manifest.path)
            if resolved is not None:
                self.by_path[resolved] = manifest
        self._by_coordinate: Optional[Dict[tuple[str, str], List[McpRegistryNpmPackageBlock]]] = (
            None
        )

    def at(self, path: Optional[Path]) -> Optional[McpRegistryNpmPackageBlock]:
        return self.by_path.get(path) if path is not None else None

    def exact(self, identifier: str, version: str) -> List[McpRegistryNpmPackageBlock]:
        if self._by_coordinate is None:
            by_coordinate: Dict[tuple[str, str], List[McpRegistryNpmPackageBlock]] = {}
            for manifest in self.by_path.values():
                data = manifest.raw_data
                if not isinstance(data, dict):
                    continue
                name = data.get("name")
                package_version = data.get("version")
                if isinstance(name, str) and isinstance(package_version, str):
                    by_coordinate.setdefault((name, package_version), []).append(manifest)
            self._by_coordinate = by_coordinate
        return self._by_coordinate.get((identifier, version), [])


class McpRegistryNpmNameMatchRule(Rule):
    """Check local npm package identity against Registry publisher identity."""

    repo_types = MCP_REGISTRY_REPO_TYPES
    since = "0.20.0"
    target_dependencies = ("mcp-registry-server-json-valid",)

    @property
    def rule_id(self) -> str:
        return "mcp-registry-npm-name-match"

    @property
    def description(self) -> str:
        return "Local npm package.json mcpName must match MCP Registry server.json name"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        references: List[_NpmReference] = []
        for block in context.lint_tree.find(McpRegistryServerBlock):
            if (
                block.parse_error
                or block.raw_data is None
                or declares_unsupported_schema(block.raw_data)
            ):
                continue
            server_name = block.raw_data.get("name")
            packages = block.raw_data.get("packages")
            if not isinstance(server_name, str) or not isinstance(packages, list):
                continue
            schema_version = (
                mcp_registry_schema_version(block.raw_data.get("$schema"))
                or MCP_REGISTRY_SCHEMA_VERSION
            )
            schema_profile = MCP_REGISTRY_SCHEMA_PROFILES.get(schema_version)
            if schema_profile is None:
                continue
            for package in packages:
                if (
                    not isinstance(package, dict)
                    or package.get(schema_profile.registry_type_field) != "npm"
                ):
                    continue
                identifier = package.get("identifier")
                if not isinstance(identifier, str):
                    continue
                package_version = package.get("version")
                if not isinstance(package_version, str):
                    # A missing or malformed version cannot identify the exact
                    # local artifact whose published metadata Registry checks.
                    continue
                references.append(_NpmReference(block, server_name, identifier, package_version))

        if not references:
            return []

        candidates = self._package_candidates(context)
        violations: List[RuleViolation] = []
        checked: set[tuple[Path, str, str]] = set()
        for reference in references:
            manifest = self._local_manifest(context, reference, candidates)
            if manifest is None:
                continue
            manifest_path = manifest.path
            data = manifest.raw_data
            key = (manifest_path, reference.identifier, reference.server_name)
            if key in checked:
                continue
            checked.add(key)
            if not isinstance(data, dict):
                continue
            mcp_name = data.get("mcpName")
            if mcp_name is None:
                message = (
                    "Local npm package.json must declare 'mcpName' "
                    f"equal to {safe_display(reference.server_name)!r}"
                )
            elif not isinstance(mcp_name, str):
                message = "Local npm package.json 'mcpName' must be a string"
            elif mcp_name != reference.server_name:
                message = (
                    "Local npm package.json 'mcpName' must exactly match "
                    f"server.json name {safe_display(reference.server_name)!r}"
                )
            else:
                continue
            violations.append(
                self.violation(
                    message,
                    file_path=manifest_path,
                    fingerprint_discriminator=(
                        f"npm:{stable_key((reference.identifier, reference.server_name))}:mcp-name"
                    ),
                )
            )
        return violations

    @staticmethod
    def _package_candidates(
        context: RepositoryContext,
    ) -> _PackageCandidates:
        """Collect typed manifests without parsing them until evidence requires it."""
        return _PackageCandidates(context.lint_tree.find(McpRegistryNpmPackageBlock))

    def _local_manifest(
        self,
        context: RepositoryContext,
        reference: _NpmReference,
        candidates: _PackageCandidates,
    ) -> Optional[McpRegistryNpmPackageBlock]:
        """Return one manifest connected to the publisher by path evidence."""
        root = safe_resolve(context.root_path)
        server_path = safe_resolve(reference.server.path)
        if root is None or server_path is None or not server_path.is_relative_to(root):
            return None

        repository = reference.server.raw_data.get("repository")
        nearest_boundary = None
        directory = server_path.parent
        while directory.is_relative_to(root):
            candidate_path = safe_resolve(directory / "package.json")
            candidate = candidates.at(candidate_path)
            if candidate is not None:
                nearest_boundary = candidate
                break
            if directory == root:
                break
            directory = directory.parent
        if nearest_boundary is not None and self._coordinates_match(nearest_boundary, reference):
            return nearest_boundary

        subfolder = repository.get("subfolder") if isinstance(repository, dict) else None
        if isinstance(subfolder, str) and is_clean_repository_subfolder(subfolder):
            candidate_path = safe_resolve(root / subfolder / "package.json")
            candidate = candidates.at(candidate_path)
            if candidate is not None:
                return candidate if self._coordinates_match(candidate, reference) else None

        # Do not search across an enclosing package boundary that identifies
        # a different artifact. Explicit repository.subfolder evidence above
        # is the only safe way to cross it.
        if nearest_boundary is not None:
            return None

        corroborated = [
            manifest
            for manifest in candidates.exact(reference.identifier, reference.version)
            if self._repository_location_matches(root, manifest, repository)
        ]
        return corroborated[0] if len(corroborated) == 1 else None

    @staticmethod
    def _coordinates_match(
        manifest: McpRegistryNpmPackageBlock,
        reference: _NpmReference,
    ) -> bool:
        data = manifest.raw_data
        if not isinstance(data, dict) or data.get("name") != reference.identifier:
            return False
        return data.get("version") == reference.version

    @staticmethod
    def _repository_location_matches(
        root: Path,
        manifest: McpRegistryNpmPackageBlock,
        server_repository: object,
    ) -> bool:
        """Require both repository identity and an exact package-directory claim."""
        data = manifest.raw_data
        package_repository = data.get("repository") if isinstance(data, dict) else None
        if not isinstance(server_repository, dict) or not isinstance(package_repository, dict):
            return False
        server_url = _canonical_repository_url(server_repository.get("url"))
        package_url = _canonical_repository_url(package_repository.get("url"))
        directory = package_repository.get("directory")
        if (
            server_url is None
            or package_url != server_url
            or not isinstance(directory, str)
            or not is_clean_repository_subfolder(directory)
        ):
            return False
        manifest_path = safe_resolve(manifest.path)
        declared_path = safe_resolve(root / directory / "package.json")
        return manifest_path is not None and manifest_path == declared_path


def _canonical_repository_url(value: object) -> Optional[str]:
    """Normalize common npm Git URL spellings for identity comparison only."""
    if not isinstance(value, str):
        return None
    url = value.strip()
    if url.startswith("git+"):
        url = url[4:]
    if url.startswith("git@") and ":" in url:
        authority, path = url.split(":", 1)
        url = f"ssh://{authority}/{path}"
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return None
    if (
        hostname is None
        or parsed.password is not None
        or (parsed.username is not None and parsed.username != "git")
    ):
        return None
    path = parsed.path.rstrip("/")
    if path.endswith(".git"):
        path = path[:-4]
    authority = hostname.lower() if port is None else f"{hostname.lower()}:{port}"
    return f"{authority}{path}"

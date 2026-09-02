"""Rule: mcp-registry-npm-name-match."""

from __future__ import annotations

import fnmatch
import re
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
    is_release_source_placeholder,
    stable_key,
)

_GITHUB_REPOSITORY_SHORTCUT = re.compile(r"\A[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:#[^\s/#]+)?\Z")


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
    target_dependency_scopes = {
        "mcp-registry-server-json-valid": (McpRegistryServerBlock,),
    }

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
            if (
                not isinstance(server_name, str)
                or is_release_source_placeholder(server_name)
                or not isinstance(packages, list)
            ):
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
                if not isinstance(identifier, str) or is_release_source_placeholder(identifier):
                    continue
                package_version = package.get("version")
                if not isinstance(package_version, str) or is_release_source_placeholder(
                    package_version
                ):
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
        exact = candidates.exact(reference.identifier, reference.version)
        located = [
            manifest
            for manifest in exact
            if self._repository_directory_matches(root, manifest, repository)
        ]
        if located:
            return located[0] if len(located) == 1 else None

        nearest_boundary = None
        directory = server_path.parent
        while directory.is_relative_to(root):
            candidate_path = safe_resolve(directory / "package.json")
            candidate = (
                candidates.at(candidate_path)
                if candidate_path is not None and candidate_path.is_relative_to(root)
                else None
            )
            if candidate is not None:
                nearest_boundary = candidate
                break
            if directory == root:
                break
            directory = directory.parent
        if nearest_boundary is not None and self._coordinates_match(nearest_boundary, reference):
            # An npm-workspaces container can carry the published package's
            # own name and version (`experimental/tailscale/package.json`
            # declaring `workspaces: ["local"]` beside `local/package.json`,
            # which is what npm publishes and what carries `mcpName`). The
            # container is never published; the member is the package.
            member = self._unique_workspace_member(root, nearest_boundary, exact)
            if member is not None:
                return member
            return (
                nearest_boundary
                if self._nearest_repository_matches(root, nearest_boundary, repository)
                else None
            )

        # Do not search across a package boundary that identifies a different
        # artifact. A workspace container — a private root package, or any
        # manifest declaring `workspaces` — is not an artifact; nested or
        # publishable boundaries remain authoritative.
        if (
            nearest_boundary is not None
            and not self._is_private_root_container(root, nearest_boundary)
            and not self._declares_workspaces(nearest_boundary)
        ):
            return None

        if len(exact) != 1:
            return None
        fallback = exact[0]
        if not self._repository_matches(root, fallback, repository):
            return None
        return fallback if self._fallback_path_is_unambiguous(root, fallback, candidates) else None

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
    def _declares_workspaces(manifest: McpRegistryNpmPackageBlock) -> bool:
        """Whether *manifest* is an npm-workspaces container."""
        data = manifest.raw_data
        return isinstance(data, dict) and isinstance(data.get("workspaces"), (list, dict))

    @classmethod
    def _unique_workspace_member(
        cls,
        root: Path,
        container: McpRegistryNpmPackageBlock,
        exact: List[McpRegistryNpmPackageBlock],
    ) -> Optional[McpRegistryNpmPackageBlock]:
        """The one manifest below a workspaces container with the same coordinates."""
        if not cls._declares_workspaces(container):
            return None
        container_dir = safe_resolve(container.path.parent)
        if container_dir is None:
            return None
        patterns = cls._workspace_patterns(container)
        members = []
        for manifest in exact:
            if manifest is container:
                continue
            manifest_path = safe_resolve(manifest.path)
            if (
                manifest_path is None
                or not manifest_path.is_relative_to(container_dir)
                or not manifest_path.is_relative_to(root)
            ):
                continue
            # Only a directory the container actually declares is a member:
            # `workspaces: ["packages/*"]` does not make `examples/foo` one.
            member_dir = manifest_path.parent.relative_to(container_dir).as_posix()
            if any(fnmatch.fnmatchcase(member_dir, pattern) for pattern in patterns):
                members.append(manifest)
        return members[0] if len(members) == 1 else None

    @staticmethod
    def _workspace_patterns(container: McpRegistryNpmPackageBlock) -> List[str]:
        """The directory globs a ``workspaces`` field declares, in either shape."""
        data = container.raw_data
        value = data.get("workspaces") if isinstance(data, dict) else None
        if isinstance(value, dict):
            value = value.get("packages")
        if not isinstance(value, list):
            return []
        return [
            pattern.strip().rstrip("/")
            for pattern in value
            if isinstance(pattern, str) and pattern.strip()
        ]

    @staticmethod
    def _is_private_root_container(
        root: Path,
        manifest: McpRegistryNpmPackageBlock,
    ) -> bool:
        """Return whether *manifest* is the repository's private root package."""
        data = manifest.raw_data
        manifest_path = safe_resolve(manifest.path)
        root_manifest = safe_resolve(root / "package.json")
        return (
            isinstance(data, dict)
            and data.get("private") is True
            and manifest_path is not None
            and manifest_path == root_manifest
        )

    @classmethod
    def _repository_matches(
        cls,
        root: Path,
        manifest: McpRegistryNpmPackageBlock,
        server_repository: object,
    ) -> bool:
        """Require repository identity and honor an optional package directory."""
        data = manifest.raw_data
        package_repository = data.get("repository") if isinstance(data, dict) else None
        if not isinstance(server_repository, dict) or not isinstance(
            package_repository, (dict, str)
        ):
            return False
        server_url = _canonical_repository_url(server_repository.get("url"))
        package_url = _canonical_repository_url(
            package_repository.get("url")
            if isinstance(package_repository, dict)
            else package_repository
        )
        if server_url is None or package_url != server_url:
            return False
        return cls._repository_path_matches(root, manifest, package_repository)

    @staticmethod
    def _repository_path_matches(
        root: Path,
        manifest: McpRegistryNpmPackageBlock,
        package_repository: object,
    ) -> bool:
        """Honor a package's directory claim and repository containment."""
        manifest_path = safe_resolve(manifest.path)
        if manifest_path is None or not manifest_path.is_relative_to(root):
            return False
        if not isinstance(package_repository, dict) or "directory" not in package_repository:
            return True
        directory = package_repository.get("directory")
        if not isinstance(directory, str) or not is_clean_repository_subfolder(directory):
            return False
        declared_path = safe_resolve(root / directory / "package.json")
        return manifest_path == declared_path

    @classmethod
    def _repository_directory_matches(
        cls,
        root: Path,
        manifest: McpRegistryNpmPackageBlock,
        server_repository: object,
    ) -> bool:
        """Return whether an exact package directory corroborates the path."""
        data = manifest.raw_data
        package_repository = data.get("repository") if isinstance(data, dict) else None
        return (
            isinstance(package_repository, dict)
            and "directory" in package_repository
            and cls._repository_matches(root, manifest, server_repository)
        )

    @classmethod
    def _nearest_repository_matches(
        cls,
        root: Path,
        manifest: McpRegistryNpmPackageBlock,
        server_repository: object,
    ) -> bool:
        """Honor repository metadata when a nearest manifest declares it."""
        data = manifest.raw_data
        package_repository = data.get("repository") if isinstance(data, dict) else None
        if not cls._repository_path_matches(root, manifest, package_repository):
            return False
        if package_repository is None:
            return True
        server_url = (
            _canonical_repository_url(server_repository.get("url"))
            if isinstance(server_repository, dict)
            else None
        )
        if server_url is None:
            return True
        package_url = _canonical_repository_url(
            package_repository.get("url")
            if isinstance(package_repository, dict)
            else package_repository
        )
        return package_url == server_url

    @classmethod
    def _fallback_path_is_unambiguous(
        cls,
        root: Path,
        manifest: McpRegistryNpmPackageBlock,
        candidates: _PackageCandidates,
    ) -> bool:
        """Reject global fallback through another local package boundary."""
        manifest_path = safe_resolve(manifest.path)
        if manifest_path is None or not manifest_path.is_relative_to(root):
            return False
        directory = manifest_path.parent.parent
        while directory.is_relative_to(root):
            boundary = candidates.at(safe_resolve(directory / "package.json"))
            if (
                boundary is not None
                and not cls._is_private_root_container(root, boundary)
                and not cls._declares_workspaces(boundary)
            ):
                return False
            if directory == root:
                break
            directory = directory.parent
        return True


def _canonical_repository_url(value: object) -> Optional[str]:
    """Normalize common npm Git URL spellings for identity comparison only."""
    if not isinstance(value, str):
        return None
    url = value.strip()
    if _GITHUB_REPOSITORY_SHORTCUT.fullmatch(url):
        url = f"https://github.com/{url}"
    for prefix, host in (("github:", "github.com"), ("gitlab:", "gitlab.com")):
        if url.startswith(prefix):
            url = f"https://{host}/{url.removeprefix(prefix)}"
            break
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
    normalized_host = hostname.lower()
    if normalized_host in {"www.github.com", "www.gitlab.com"}:
        normalized_host = normalized_host.removeprefix("www.")
    if normalized_host == "github.com":
        path = path.casefold()
    authority = normalized_host if port is None else f"{normalized_host}:{port}"
    return f"{authority}{path}"

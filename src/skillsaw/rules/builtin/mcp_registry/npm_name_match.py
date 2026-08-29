"""Rule: mcp-registry-npm-name-match."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

from skillsaw.blocks import McpRegistryNpmPackageBlock, McpRegistryServerBlock
from skillsaw.context import RepositoryContext
from skillsaw.diagnostics import safe_display
from skillsaw.rule import Rule, RuleViolation, Severity

from ._helpers import MCP_REGISTRY_REPO_TYPES, stable_key

_MISSING = object()


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
        references: List[Tuple[str, str, object]] = []
        for block in context.lint_tree.find(McpRegistryServerBlock):
            if block.parse_error or block.raw_data is None:
                continue
            server_name = block.raw_data.get("name")
            packages = block.raw_data.get("packages")
            if not isinstance(server_name, str) or not isinstance(packages, list):
                continue
            for package in packages:
                if not isinstance(package, dict) or package.get("registryType") != "npm":
                    continue
                identifier = package.get("identifier")
                if not isinstance(identifier, str):
                    continue
                package_version = package.get("version", _MISSING)
                if package_version is not _MISSING and not isinstance(package_version, str):
                    # Schema validation owns malformed declared versions. An
                    # invalid value cannot identify a local published release.
                    continue
                references.append((server_name, identifier, package_version))

        if not references:
            return []

        by_name = self._package_index(context)
        violations: List[RuleViolation] = []
        checked: set[Tuple[Path, str, str]] = set()
        for server_name, identifier, package_version in references:
            candidates = [
                manifest
                for manifest in by_name.get(identifier, ())
                if package_version is _MISSING
                or (
                    isinstance(manifest.raw_data, dict)
                    and manifest.raw_data.get("version") == package_version
                )
            ]
            for manifest in candidates:
                manifest_path = manifest.path
                data = manifest.raw_data
                key = (manifest_path, identifier, server_name)
                if key in checked:
                    continue
                checked.add(key)
                if not isinstance(data, dict):
                    continue
                mcp_name = data.get("mcpName")
                if mcp_name is None:
                    message = (
                        "Local npm package.json must declare 'mcpName' "
                        f"equal to {safe_display(server_name)!r}"
                    )
                elif not isinstance(mcp_name, str):
                    message = "Local npm package.json 'mcpName' must be a string"
                elif mcp_name != server_name:
                    message = (
                        "Local npm package.json 'mcpName' must exactly match "
                        f"server.json name {safe_display(server_name)!r}"
                    )
                else:
                    continue
                violations.append(
                    self.violation(
                        message,
                        file_path=manifest_path,
                        fingerprint_discriminator=(
                            f"npm:{stable_key((identifier, server_name))}:mcp-name"
                        ),
                    )
                )
        return violations

    @staticmethod
    def _package_index(
        context: RepositoryContext,
    ) -> Dict[str, List[McpRegistryNpmPackageBlock]]:
        """Index typed local package-manifest targets by npm name."""
        by_name: Dict[str, List[McpRegistryNpmPackageBlock]] = {}
        for manifest in context.lint_tree.find(McpRegistryNpmPackageBlock):
            data = manifest.raw_data
            package_name = data.get("name") if isinstance(data, dict) else None
            if isinstance(package_name, str):
                by_name.setdefault(package_name, []).append(manifest)
        return by_name

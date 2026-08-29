"""Rule: mcp-registry-npm-name-match."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

from skillsaw.blocks import McpRegistryServerBlock
from skillsaw.context import RepositoryContext
from skillsaw.diagnostics import safe_display
from skillsaw.paths import contained_resolve, safe_is_file, safe_resolve
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.utils import read_json_strict

from ._helpers import MCP_REGISTRY_REPO_TYPES, stable_key


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
        by_name, by_directory = self._package_index(context)
        violations: List[RuleViolation] = []
        checked: set[Tuple[Path, str, str]] = set()
        unverifiable: set[Path] = set()
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
                candidates = list(by_name.get(identifier, ()))
                adjacent = by_directory.get(block.path.parent)
                if (
                    not candidates
                    and adjacent is not None
                    and (adjacent[2] is not None or not isinstance(adjacent[1], dict))
                ):
                    candidates = [adjacent]
                for manifest_path, data, error in candidates:
                    key = (manifest_path, identifier, server_name)
                    if key in checked:
                        continue
                    checked.add(key)
                    if error is not None:
                        if manifest_path in unverifiable:
                            continue
                        unverifiable.add(manifest_path)
                        violations.append(
                            self.violation(
                                "Local npm package.json is invalid JSON, so its "
                                "mcpName cannot be verified",
                                file_path=manifest_path,
                                fingerprint_discriminator=(
                                    f"npm:{stable_key(identifier)}:invalid-json"
                                ),
                            )
                        )
                        continue
                    if not isinstance(data, dict):
                        if manifest_path in unverifiable:
                            continue
                        unverifiable.add(manifest_path)
                        violations.append(
                            self.violation(
                                "Local npm package.json must contain a JSON object "
                                "so its mcpName can be verified",
                                file_path=manifest_path,
                                fingerprint_discriminator=(
                                    f"npm:{stable_key(identifier)}:not-object"
                                ),
                            )
                        )
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
    ) -> tuple[
        Dict[str, List[Tuple[Path, Any, Any]]],
        Dict[Path, Tuple[Path, Any, Any]],
    ]:
        """Read local package manifests once and index them by npm name."""
        root = safe_resolve(context.root_path)
        if root is None:
            return {}, {}
        by_name: Dict[str, List[Tuple[Path, Any, Any]]] = {}
        by_directory: Dict[Path, Tuple[Path, Any, Any]] = {}
        for manifest_path in context.package_json_paths():
            resolved = contained_resolve(manifest_path, root)
            if resolved is None or not safe_is_file(resolved):
                continue
            data, error = read_json_strict(resolved)
            record = (manifest_path, data, error)
            by_directory[manifest_path.parent] = record
            package_name = data.get("name") if isinstance(data, dict) else None
            if isinstance(package_name, str):
                by_name.setdefault(package_name, []).append(record)
        return by_name, by_directory

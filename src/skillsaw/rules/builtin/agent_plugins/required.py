"""Opt-in rule requiring plugins to ship the vendor-neutral format."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from skillsaw.context import RepositoryContext
from skillsaw.paths import safe_resolve
from skillsaw.port import (
    normalize_name,
    read_source_manifest,
    read_source_mcp,
    render_mcp,
    plan_port,
)
from skillsaw.rule import AutofixConfidence, AutofixResult, Rule, RuleViolation, Severity
from skillsaw.utils import read_json

# Manifest fields both formats express (Agent Plugins spec §5.3-5.4).
_SHARED_FIELDS = (
    "name",
    "version",
    "description",
    "author",
    "homepage",
    "repository",
    "license",
    "keywords",
)


class AgentPluginRequiredRule(Rule):
    """Require every Claude/Codex plugin to also be an Agent Plugins package."""

    default_enabled = False
    since = "0.18.0"
    autofix_confidence = AutofixConfidence.SAFE

    @property
    def rule_id(self) -> str:
        return "agent-plugin-required"

    @property
    def description(self) -> str:
        return (
            "Plugins must also be available as vendor-neutral Agent Plugins v1 "
            "packages, with shared manifest metadata in sync"
        )

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        # Ownership comes from discovery's verdicts, not a fresh filesystem
        # probe (see the ecosystem-provenance development rule): a directory
        # is an Agent Plugins package iff discovery already claimed it.
        agent_plugin_roots = {safe_resolve(p) or p for p in getattr(context, "agent_plugins", [])}
        for plugin_dir in context.distinct_plugin_dirs():
            source, _sources, _notes = read_source_manifest(plugin_dir)
            if source is None:
                continue

            if (safe_resolve(plugin_dir) or plugin_dir) not in agent_plugin_roots:
                fixable = bool(plan_port(plugin_dir).writes)
                violations.append(
                    self.violation(
                        "Plugin is not available as an Agent Plugins v1 package — "
                        "add a root plugin.json declaring the schema "
                        "(skillsaw port --to agent-plugin, or skillsaw fix)",
                        file_path=plugin_dir / "plugin.json",
                        fixable=fixable,
                    )
                )
                continue

            portable = read_json(plugin_dir / "plugin.json")[0]
            if isinstance(portable, dict):
                for field in self._drifted_fields(source, portable):
                    violations.append(
                        self.violation(
                            f"'{field}' differs between the source manifest and the "
                            "portable plugin.json — keep shared metadata in sync",
                            file_path=plugin_dir / "plugin.json",
                            fixable=False,
                        )
                    )

            if (plugin_dir / ".mcp.json").is_file() and not (plugin_dir / "mcp.json").is_file():
                violations.append(
                    self.violation(
                        "Claude MCP configuration (.mcp.json) has no portable "
                        "mcp.json counterpart",
                        file_path=plugin_dir / "mcp.json",
                        # Not fixable when no server survives translation.
                        fixable=self._portable_mcp(plugin_dir) is not None,
                    )
                )
        return violations

    @staticmethod
    def _drifted_fields(source: Dict[str, Any], portable: Dict[str, Any]) -> List[str]:
        """Shared fields present in both manifests whose values disagree.

        Each source value is normalized the same way the port renders it,
        so a clean port never reads as drift.
        """
        drifted = []
        for field in _SHARED_FIELDS:
            if field not in source or field not in portable:
                continue
            left, right = source[field], portable[field]
            if field == "name" and isinstance(left, str):
                left = normalize_name(left) or left
            if field == "author":
                if isinstance(left, str):
                    left = {"name": left}
                elif isinstance(left, dict):
                    left = {
                        k: v
                        for k, v in left.items()
                        if k in ("name", "email", "url") and isinstance(v, str)
                    }
            if left != right:
                drifted.append(field)
        return drifted

    def fix(
        self, context: RepositoryContext, violations: List[RuleViolation]
    ) -> List[AutofixResult]:
        results: List[AutofixResult] = []
        for v in violations:
            if v.file_path is None:
                continue
            plugin_dir = v.file_path.parent
            if "not available as an Agent Plugins" in v.message:
                plan = plan_port(plugin_dir)
                for filename, content in plan.writes.items():
                    results.append(
                        AutofixResult(
                            rule_id=self.rule_id,
                            file_path=plugin_dir / filename,
                            confidence=AutofixConfidence.SAFE,
                            original_content="",
                            fixed_content=content,
                            description=f"Created portable {filename} from the source manifest",
                            violations_fixed=[v] if filename == "plugin.json" else [],
                        )
                    )
            elif "no portable" in v.message:
                content = self._portable_mcp(plugin_dir)
                if content is not None:
                    results.append(
                        AutofixResult(
                            rule_id=self.rule_id,
                            file_path=plugin_dir / "mcp.json",
                            confidence=AutofixConfidence.SAFE,
                            original_content="",
                            fixed_content=content,
                            description="Created portable mcp.json from .mcp.json",
                            violations_fixed=[v],
                        )
                    )
        return results

    @staticmethod
    def _portable_mcp(plugin_dir: Path) -> Optional[str]:
        servers = read_source_mcp(plugin_dir)
        if servers is None:
            return None
        return render_mcp(servers, notes=[])

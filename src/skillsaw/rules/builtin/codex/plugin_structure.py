"""
Rule: codex-plugin-structure
"""

from pathlib import Path, PurePosixPath
from typing import List, Set

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.lint_target import CodexPluginConfigNode
from skillsaw.formats.codex import CODEX_INTERFACE_ASSET_FIELDS
from skillsaw.paths import contained_resolve, safe_is_file, safe_resolve
from skillsaw.utils import read_json

from skillsaw.diagnostics import safe_display

from ._helpers import CODEX_PLUGIN_REPO_TYPES


class CodexPluginStructureRule(Rule):
    """Check the layout of a Codex plugin directory"""

    repo_types = CODEX_PLUGIN_REPO_TYPES
    since = "0.18.0"

    @property
    def rule_id(self) -> str:
        return "codex-plugin-structure"

    @property
    def description(self) -> str:
        return ".codex-plugin/ should contain only its manifest and referenced interface assets"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []

        for node in context.lint_tree.find(CodexPluginConfigNode):
            if context.is_codex_installed_plugin(node.plugin_dir):
                # Layout of a plugin the repository installed rather than
                # wrote, so its structure is not this repository's to fix.
                # See codex-plugin-json-valid.
                continue
            manifest_dir = node.path.parent
            asset_entries = _referenced_asset_entries(node)
            try:
                entries = sorted(manifest_dir.iterdir())
            except OSError:
                continue

            for entry in entries:
                if entry.name == "plugin.json" or entry.name in asset_entries:
                    continue
                violations.append(
                    self.violation(
                        f"'{safe_display(entry.name)}' does not belong in .codex-plugin/ — keep "
                        "skills/, hooks/, assets/, .mcp.json and .app.json at the "
                        "plugin root",
                        file_path=entry,
                    )
                )

        return violations


def _referenced_asset_entries(node: CodexPluginConfigNode) -> Set[str]:
    """Manifest-directory entries containing an explicitly named local asset.

    Assets are loaded by path, not conventional discovery. The official
    openai/plugins catalog uses .codex-plugin/assets/ for several plugins;
    treating those referenced files as undiscoverable is a false positive.
    Missing, malformed and escaping paths earn no layout exemption.
    """
    data, error = read_json(node.path)
    if error or not isinstance(data, dict) or not isinstance(data.get("interface"), dict):
        return set()
    root = safe_resolve(node.plugin_dir)
    if root is None:
        return set()
    entries = set()
    for field in CODEX_INTERFACE_ASSET_FIELDS:
        value = data["interface"].get(field)
        values = value if isinstance(value, list) else [value]
        for value in values:
            if not isinstance(value, str) or not value.startswith("./"):
                continue
            parts = PurePosixPath(value).parts
            if len(parts) < 2 or parts[0] != ".codex-plugin" or ".." in parts:
                continue
            target = contained_resolve(node.plugin_dir / Path(value), root)
            if target is not None and safe_is_file(target):
                entries.add(parts[1])
    return entries

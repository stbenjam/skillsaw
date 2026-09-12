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
            assets = _referenced_assets(node)
            try:
                entries = sorted(manifest_dir.iterdir(), reverse=True)
            except OSError:
                continue

            while entries:
                entry = entries.pop()
                if entry == node.path or entry in assets:
                    continue
                # Descend only along explicitly referenced paths. A sibling
                # asset or misplaced hook does not inherit the exemption.
                if any(asset.is_relative_to(entry) for asset in assets):
                    try:
                        entries.extend(sorted(entry.iterdir(), reverse=True))
                        continue
                    except OSError:
                        pass
                violations.append(
                    self.violation(
                        f"'{safe_display(entry.relative_to(manifest_dir))}' does not belong in .codex-plugin/ — keep "
                        "skills/, hooks/, assets/, .mcp.json and .app.json at the "
                        "plugin root",
                        file_path=entry,
                    )
                )

        return violations


def _referenced_assets(node: CodexPluginConfigNode) -> Set[Path]:
    """Existing, explicitly named local assets in the manifest directory.

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
    for field, expected_type in CODEX_INTERFACE_ASSET_FIELDS.items():
        value = data["interface"].get(field)
        if not isinstance(value, expected_type):
            continue
        values = value if isinstance(value, list) else [value]
        for value in values:
            if not isinstance(value, str) or not value.startswith("./"):
                continue
            parts = PurePosixPath(value).parts
            if len(parts) < 2 or parts[0] != ".codex-plugin" or ".." in parts:
                continue
            target = contained_resolve(node.plugin_dir / Path(value), root)
            if target is not None and safe_is_file(target):
                entries.add(node.plugin_dir.joinpath(*parts))
    return entries

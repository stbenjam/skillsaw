"""
Rule: codex-plugin-structure
"""

from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.lint_target import CodexPluginConfigNode
from skillsaw.paths import contained_resolve, safe_resolve

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
        return "Only plugin.json belongs in .codex-plugin/"

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
            # Inline metadata changes the selected manifest, not the reserved
            # directory's layout requirement. Inspect it when it still exists.
            root = safe_resolve(node.plugin_dir)
            manifest_dir = node.plugin_dir / ".codex-plugin"
            if root is None or contained_resolve(manifest_dir, root) is None:
                continue
            try:
                entries = sorted(manifest_dir.iterdir())
            except OSError:
                continue

            for entry in entries:
                if entry.name == "plugin.json":
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

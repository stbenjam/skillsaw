"""
Rule: codex-plugin-structure
"""

from pathlib import Path
from typing import Any, List, Set

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.lint_target import CodexPluginConfigNode

from skillsaw.diagnostics import safe_display

from skillsaw.rules.builtin.utils import read_json

from ._helpers import CODEX_PLUGIN_REPO_TYPES

_MANIFEST_DIR = ".codex-plugin"


def _self_referenced_paths(data: Any) -> Set[str]:
    """Manifest-root-relative paths the manifest points at inside ``.codex-plugin/``.

    The official catalog (openai/plugins) ships ``interface`` assets under
    ``.codex-plugin/assets/`` and references them as
    ``"./.codex-plugin/assets/logo.png"``, so Codex loads them and they are
    not stray files. Every string in the document is considered rather than
    a list of known path fields: a field list would have to be kept in step
    with ``plugin_json_valid``'s, and missing an entry there turns into a
    false positive here. The cost is that a prose value which happens to
    spell a ``.codex-plugin/`` path also suppresses the warning, which only
    ever loses a warning about a stray file.
    """
    found: Set[str] = set()

    def _walk(value: Any) -> None:
        if isinstance(value, str):
            candidate = value[2:] if value.startswith("./") else value
            if candidate.startswith(f"{_MANIFEST_DIR}/"):
                found.add(candidate)
        elif isinstance(value, list):
            for item in value:
                _walk(item)
        elif isinstance(value, dict):
            for item in value.values():
                _walk(item)

    _walk(data)
    return found


def _is_referenced(entry: Path, manifest_dir: Path, referenced: Set[str]) -> bool:
    """Whether *entry* is, or contains, something the manifest points at."""
    try:
        relative = entry.relative_to(manifest_dir.parent).as_posix()
    except ValueError:
        return False
    return any(ref == relative or ref.startswith(f"{relative}/") for ref in referenced)


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
            manifest_dir = node.path.parent
            try:
                entries = sorted(manifest_dir.iterdir())
            except OSError:
                continue

            # A manifest that does not parse is codex-plugin-json-valid's
            # to report; here it just means nothing is referenced.
            data, _error = read_json(node.path)
            referenced = _self_referenced_paths(data)

            for entry in entries:
                if entry.name == "plugin.json":
                    continue
                if _is_referenced(entry, manifest_dir, referenced):
                    # The manifest points at it, so Codex loads it from
                    # here — it is placed unconventionally, not stray.
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

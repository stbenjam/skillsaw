"""Diagnose a requested Codex project instruction chain and byte cap."""

from typing import List

from skillsaw.codex_instructions import CodexInstructionsNode
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.diagnostics import safe_display
from skillsaw.paths import relative_to_str
from skillsaw.rule import Rule, RuleViolation, Severity


class CodexProjectInstructionsRule(Rule):
    since = "0.21.1"
    default_enabled = False
    repo_types = frozenset({RepositoryType.AGENTS_MD, RepositoryType.CODEX_PROJECT})

    @property
    def rule_id(self) -> str:
        return "codex-project-instructions"

    @property
    def description(self) -> str:
        return "Diagnose Codex instruction selection and the cumulative project byte limit"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        for node in context.lint_tree.find(CodexInstructionsNode):
            report = node.report(context.lint_tree)
            if not report["complete"]:
                message = "Codex instruction analysis is incomplete: " + "; ".join(
                    safe_display(issue) for issue in report["issues"][:3]
                )
            elif report["affected_paths"]:
                message = (
                    f"Codex project instructions for cwd '{safe_display(relative_to_str(node.cwd, context.root_path))}' select "
                    f"{report['selected_file_bytes']:,} file bytes; project_doc_max_bytes="
                    f"{node.max_bytes:,} ({safe_display(node.limit_source)}) truncates or omits: "
                    + ", ".join(safe_display(path) for path in report["affected_paths"][:3])
                    + (
                        f" (and {len(report['affected_paths']) - 3} more)"
                        if len(report["affected_paths"]) > 3
                        else ""
                    )
                    + ". Reduce the selected chain or raise Codex's project_doc_max_bytes. "
                    "Assumes a trusted project; global/profile/CLI config is not read. "
                    "Inspect the chain with skillsaw tree --codex-instructions."
                )
            else:
                continue
            violations.append(self.violation(message, file_path=node.path))
        return violations

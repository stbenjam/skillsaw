"""
Rule: instruction-imports-valid
"""

from pathlib import Path
import re
from typing import Dict, List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext, ALL_INSTRUCTION_FORMATS
from skillsaw.markdown_doc import MarkdownDoc
from skillsaw.rules.builtin.content_analysis import (
    AgentsMdBlock,
    ClaudeMdBlock,
    GeminiMdBlock,
    QwenMdBlock,
)
from skillsaw.rules.builtin.utils import read_text

from ._helpers import iter_markdown_instruction_imports
from skillsaw.paths import safe_exists, safe_is_file, safe_resolve

_MAX_IMPORT_HOPS = 4
_GITHUB_TEAM_MENTION_RE = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38}[A-Za-z0-9])?/"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38}[A-Za-z0-9])?"
)
_IMPORT_FILE_EXTENSIONS = {
    "adoc",
    "json",
    "md",
    "markdown",
    "mdown",
    "mkd",
    "rst",
    "toml",
    "txt",
    "yaml",
    "yml",
}
_OPTIONAL_LOCAL_IMPORT_NAMES = frozenset({"AGENTS.local.md", "CLAUDE.local.md"})


class InstructionImportsValidRule(Rule):
    """Check that @import references in instruction files resolve to existing paths"""

    formats = ALL_INSTRUCTION_FORMATS

    @property
    def rule_id(self) -> str:
        return "instruction-imports-valid"

    @property
    def description(self) -> str:
        return (
            "Import references (@path) in AGENTS.md, CLAUDE.md, GEMINI.md and QWEN.md "
            "must point to existing files"
        )

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        root_path = safe_resolve(context.root_path) or context.root_path
        # Map each resolved file to the shallowest depth we have scanned it at.
        # Tracking depth (rather than a plain visited set) lets a file first
        # reached with an exhausted hop budget be re-entered when a shorter
        # path later reaches it, so its nested imports are still followed.
        seen: Dict[Path, int] = {}

        import_blocks = (
            context.lint_tree.find(AgentsMdBlock)
            + context.lint_tree.find(ClaudeMdBlock)
            + context.lint_tree.find(GeminiMdBlock)
            + context.lint_tree.find(QwenMdBlock)
        )
        for block in import_blocks:
            file_path = block.path
            if block.read_body(strip_code_blocks=False) is None:
                continue

            self._check_imports_in_doc(
                block.markdown,
                file_path,
                root_path,
                violations,
                seen,
                depth=0,
            )

        return violations

    def _check_imports_in_doc(
        self,
        markdown: MarkdownDoc,
        file_path: Path,
        root_path: Path,
        violations: List[RuleViolation],
        seen: Dict[Path, int],
        *,
        depth: int,
    ) -> None:
        resolved_file = safe_resolve(file_path) or file_path
        prev_depth = seen.get(resolved_file)
        if prev_depth is not None and prev_depth <= depth:
            # Already scanned with at least as much remaining hop budget, so
            # both its own violations and its reachable nested imports have
            # been covered. Also breaks import cycles.
            return
        # Report each file's own violations only on the first visit; a later
        # deeper-budget re-entry recurses into children without duplicating
        # the reports emitted the first time around.
        first_visit = prev_depth is None
        seen[resolved_file] = depth

        for import_ref in iter_markdown_instruction_imports(markdown):
            import_path_str = import_ref.path
            line_start_import = import_ref.line_start
            # Home-directory imports (Claude Code's ``@~/.claude/...``
            # memory syntax) reference machine-local files that are not
            # part of the repository. They're environment-specific, so
            # existence checking is always noise in CI — skip them.
            if import_path_str.startswith("~"):
                continue

            unresolved_target = resolved_file.parent / import_path_str
            target = safe_resolve(unresolved_target)
            if target is None:
                if first_visit and _should_report_missing(
                    import_path_str, line_start_import, unresolved_target
                ):
                    violations.append(
                        self.violation(
                            f"Import '@{import_path_str}' references non-existent path",
                            file_path=file_path,
                            line=import_ref.file_line,
                        )
                    )
                continue

            try:
                target.relative_to(root_path)
            except ValueError:
                if first_visit:
                    violations.append(
                        self.violation(
                            f"Import '@{import_path_str}' escapes repository root",
                            file_path=file_path,
                            line=import_ref.file_line,
                        )
                    )
                continue

            if not safe_exists(target):
                # Teams commonly commit this import while gitignoring the
                # machine-local override. Its absence is intentional; if the
                # file exists, the normal recursive validation below applies.
                if target.name in _OPTIONAL_LOCAL_IMPORT_NAMES:
                    continue
                if first_visit and _should_report_missing(
                    import_path_str, line_start_import, target
                ):
                    violations.append(
                        self.violation(
                            f"Import '@{import_path_str}' references non-existent path",
                            file_path=file_path,
                            line=import_ref.file_line,
                        )
                    )
                continue

            if depth >= _MAX_IMPORT_HOPS or not safe_is_file(target):
                continue

            content = read_text(target)
            if content is None:
                continue

            self._check_imports_in_doc(
                MarkdownDoc(content),
                target,
                root_path,
                violations,
                seen,
                depth=depth + 1,
            )


def _should_report_missing(import_path: str, line_start_import: bool, target: Path) -> bool:
    """Decide whether a missing mid-line ``@token`` is a broken import worth
    reporting or prose that merely looks like one (a mention/handle)."""
    if line_start_import:
        return True

    if import_path.startswith((".", "/")):
        return True

    if "/" in import_path:
        if _GITHUB_TEAM_MENTION_RE.fullmatch(import_path):
            # ``@org/team`` GitHub mentions and ``@docs/setup`` import paths are
            # structurally identical. Only treat the reference as a broken
            # import when its parent directory actually exists in the repo;
            # otherwise assume it's a team mention and stay quiet.
            return safe_exists(target.parent)
        return True

    if "." in import_path:
        suffix = import_path.rsplit(".", 1)[1].lower()
        return suffix in _IMPORT_FILE_EXTENSIONS

    return False

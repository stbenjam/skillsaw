"""
Rule: instruction-imports-valid
"""

from pathlib import Path
import re
from typing import Iterable, List, Set, Tuple

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext, ALL_INSTRUCTION_FORMATS
from skillsaw.markdown_doc import MarkdownDoc
from skillsaw.rules.builtin.content_analysis import (
    AgentsMdBlock,
    ClaudeMdBlock,
    GeminiMdBlock,
)
from skillsaw.rules.builtin.utils import read_text

from ._helpers import _IMPORT_RE

_MAX_IMPORT_HOPS = 4
_LINE_START_IMPORT_PREFIX_RE = re.compile(r"^\s*(?:(?:>\s*)|(?:[-*+]\s+)|(?:\d+[.)]\s+))*$")
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


class InstructionImportsValidRule(Rule):
    """Check that @import references in instruction files resolve to existing paths"""

    formats = ALL_INSTRUCTION_FORMATS

    @property
    def rule_id(self) -> str:
        return "instruction-imports-valid"

    @property
    def description(self) -> str:
        return "Import references (@path) in AGENTS.md, CLAUDE.md, and GEMINI.md must point to existing files"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        root_path = context.root_path.resolve()
        seen: Set[Path] = set()

        import_blocks = (
            context.lint_tree.find(AgentsMdBlock)
            + context.lint_tree.find(ClaudeMdBlock)
            + context.lint_tree.find(GeminiMdBlock)
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
        seen: Set[Path],
        *,
        depth: int,
    ) -> None:
        resolved_file = file_path.resolve()
        if resolved_file in seen:
            return
        seen.add(resolved_file)

        for line_num, line in markdown.prose_lines():
            for import_path_str, report_missing in _iter_import_paths(line):
                # Home-directory imports (Claude Code's ``@~/.claude/...``
                # memory syntax) reference machine-local files that are not
                # part of the repository. They're environment-specific, so
                # existence checking is always noise in CI — skip them.
                if import_path_str.startswith("~"):
                    continue

                target = (resolved_file.parent / import_path_str).resolve()

                try:
                    target.relative_to(root_path)
                except ValueError:
                    violations.append(
                        self.violation(
                            f"Import '@{import_path_str}' escapes repository root",
                            file_path=file_path,
                            line=line_num,
                        )
                    )
                    continue

                if not target.exists():
                    if not report_missing:
                        continue
                    violations.append(
                        self.violation(
                            f"Import '@{import_path_str}' references non-existent path",
                            file_path=file_path,
                            line=line_num,
                        )
                    )
                    continue

                if depth >= _MAX_IMPORT_HOPS or not target.is_file():
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


def _iter_import_paths(line: str) -> Iterable[Tuple[str, bool]]:
    for match in _IMPORT_RE.finditer(line):
        import_path = match.group(1).rstrip(".!?")
        if not import_path:
            continue

        line_start_import = bool(_LINE_START_IMPORT_PREFIX_RE.fullmatch(line[: match.start()]))
        report_missing = line_start_import or _looks_like_import_path(import_path)

        yield import_path, report_missing


def _looks_like_import_path(import_path: str) -> bool:
    if import_path.startswith((".", "/")):
        return True

    if "/" in import_path:
        if _GITHUB_TEAM_MENTION_RE.fullmatch(import_path):
            return False
        return True

    if "." in import_path:
        suffix = import_path.rsplit(".", 1)[1].lower()
        return suffix in _IMPORT_FILE_EXTENSIONS

    return False

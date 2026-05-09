"""
Rules for validating AI coding assistant instruction files
(AGENTS.md, CLAUDE.md, GEMINI.md)
"""

import re
from pathlib import Path
from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext, ALL_INSTRUCTION_FORMATS, HAS_AGENTS_MD
from skillsaw.rules.builtin.utils import read_text

INSTRUCTION_FILES = ("AGENTS.md", "CLAUDE.md", "GEMINI.md")

IMPORT_SUPPORTING_FILES = ("CLAUDE.md", "GEMINI.md")

HIERARCHICAL_FILES = ("GEMINI.md",)

_IMPORT_RE = re.compile(r"^\s*@(\S+)")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)", re.MULTILINE)
_MIN_CONTENT_CHARS = 20


def _find_hierarchical_files(root: Path, filename: str) -> List[Path]:
    """Find all instances of a file in the directory tree, skipping hidden dirs."""
    results = []
    root_resolved = root.resolve()
    root_file = root / filename
    if root_file.exists():
        results.append(root_file)
    try:
        for child in sorted(root.rglob(filename)):
            if child == root_file:
                continue
            rel = child.relative_to(root_resolved)
            if any(part.startswith(".") for part in rel.parts[:-1]):
                continue
            results.append(child)
    except OSError:
        pass
    return results


class InstructionFileValidRule(Rule):
    """Check that instruction files are valid UTF-8 and non-empty"""

    formats = ALL_INSTRUCTION_FORMATS

    @property
    def rule_id(self) -> str:
        return "instruction-file-valid"

    @property
    def description(self) -> str:
        return "Instruction files (AGENTS.md, CLAUDE.md, GEMINI.md) must be valid and non-empty"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        for filename in INSTRUCTION_FILES:
            if filename in HIERARCHICAL_FILES:
                files = _find_hierarchical_files(context.root_path, filename)
            else:
                root_file = context.root_path / filename
                files = [root_file] if root_file.exists() else []

            for file_path in files:
                content = read_text(file_path)
                if content is None:
                    violations.append(
                        self.violation(
                            f"Failed to read {filename} (invalid encoding or I/O error)",
                            file_path=file_path,
                        )
                    )
                    continue

                if not content.strip():
                    violations.append(self.violation(f"{filename} is empty", file_path=file_path))

        return violations


class InstructionImportsValidRule(Rule):
    """Check that @import references in instruction files resolve to existing paths"""

    formats = ALL_INSTRUCTION_FORMATS

    @property
    def rule_id(self) -> str:
        return "instruction-imports-valid"

    @property
    def description(self) -> str:
        return "Import references (@path) in CLAUDE.md and GEMINI.md must point to existing files"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        for filename in IMPORT_SUPPORTING_FILES:
            if filename in HIERARCHICAL_FILES:
                files = _find_hierarchical_files(context.root_path, filename)
            else:
                root_file = context.root_path / filename
                files = [root_file] if root_file.exists() else []

            for file_path in files:
                content = read_text(file_path)
                if content is None:
                    continue

                base_dir = file_path.parent

                for line_num, line in enumerate(content.splitlines(), 1):
                    match = _IMPORT_RE.match(line)
                    if not match:
                        continue

                    import_path_str = match.group(1)
                    target = (base_dir / import_path_str).resolve()

                    try:
                        target.relative_to(context.root_path.resolve())
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
                        violations.append(
                            self.violation(
                                f"Import '@{import_path_str}' references non-existent path",
                                file_path=file_path,
                                line=line_num,
                            )
                        )

        return violations


class AgentsMdStructureRule(Rule):
    """Check that AGENTS.md has reasonable markdown structure"""

    formats = {HAS_AGENTS_MD}

    @property
    def rule_id(self) -> str:
        return "agents-md-structure"

    @property
    def description(self) -> str:
        return "AGENTS.md should have at least one heading and meaningful content"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        file_path = context.root_path / "AGENTS.md"

        if not file_path.exists():
            return violations

        content = read_text(file_path)
        if content is None or not content.strip():
            return violations

        headings = _HEADING_RE.findall(content)
        if not headings:
            violations.append(
                self.violation(
                    "AGENTS.md has no markdown headings — add at least one heading to organize instructions",
                    file_path=file_path,
                )
            )

        non_heading_text = _HEADING_RE.sub("", content).strip()
        if len(non_heading_text) < _MIN_CONTENT_CHARS:
            violations.append(
                self.violation(
                    "AGENTS.md has little content beyond headings — add meaningful instructions",
                    file_path=file_path,
                )
            )

        return violations

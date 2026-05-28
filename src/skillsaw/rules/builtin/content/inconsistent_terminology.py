"""Content inconsistent terminology rule"""

import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set, Tuple

from skillsaw.rule import AutofixConfidence, Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.content_analysis import (
    gather_all_content_blocks,
)


class ContentInconsistentTerminologyRule(Rule):
    """Detect inconsistent terminology across instruction files"""

    autofix_confidence = AutofixConfidence.LLM
    formats = None
    since = "0.7.0"

    _TERM_GROUPS: List[Tuple[str, List[re.Pattern]]] = [
        (
            "directory/folder",
            [
                re.compile(r"\bdirector(?:y|ies)\b", re.IGNORECASE),
                re.compile(r"\bfolders?\b", re.IGNORECASE),
            ],
        ),
        (
            "repo/repository/codebase",
            [
                re.compile(r"\brepos?\b", re.IGNORECASE),
                re.compile(r"\brepositories\b|\brepository\b", re.IGNORECASE),
                re.compile(r"\bcodebase\b", re.IGNORECASE),
            ],
        ),
        (
            "PR/pull request/merge request",
            [
                re.compile(r"\bPRs?\b"),
                re.compile(r"\bpull\s+requests?\b", re.IGNORECASE),
                re.compile(r"\bmerge\s+requests?\b", re.IGNORECASE),
            ],
        ),
        (
            "function/method",
            [
                re.compile(r"\bfunctions?\b", re.IGNORECASE),
                re.compile(r"\bmethods?\b", re.IGNORECASE),
            ],
        ),
    ]

    MIN_FILES = 2

    @property
    def rule_id(self) -> str:
        return "content-inconsistent-terminology"

    @property
    def description(self) -> str:
        return "Detect inconsistent terminology across instruction files (e.g., mixing 'directory' and 'folder')"

    def default_severity(self) -> Severity:
        return Severity.INFO

    @property
    def llm_fix_prompt(self):
        return (
            "You are fixing AI coding assistant instruction files that use "
            "inconsistent terminology. Standardize on one term per concept "
            "across all files.\n\n"
            "Rules:\n"
            "- Pick the most common term and use it consistently\n"
            "- Prefer technical terms over informal ones (e.g., 'directory' over 'folder')\n"
            "- Update all occurrences to use the chosen term\n"
            "- Preserve markdown formatting"
        )

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        content_files = gather_all_content_blocks(context)
        if len(content_files) < self.MIN_FILES:
            return []

        violations = []
        for group_name, patterns in self._TERM_GROUPS:
            term_usage: Dict[str, int] = defaultdict(int)
            files_by_term: Dict[str, List[Path]] = defaultdict(list)
            for cf in content_files:
                body = cf.read_body()
                if not body:
                    continue
                for pattern in patterns:
                    if pattern.search(body):
                        term_usage[pattern.pattern] += 1
                        files_by_term[pattern.pattern].append(cf.path)

            used_terms = [p for p in term_usage if term_usage[p] > 0]
            if len(used_terms) >= 2:
                majority_term = max(used_terms, key=lambda p: term_usage[p])
                minority_files: Set[Path] = set()
                for term, fpaths in files_by_term.items():
                    if term != majority_term:
                        minority_files.update(fpaths)
                msg = f"Inconsistent terminology: {group_name} — multiple variants used across files. Pick one and use it consistently."
                for fpath in sorted(minority_files):
                    violations.append(self.violation(msg, file_path=fpath))

        return violations

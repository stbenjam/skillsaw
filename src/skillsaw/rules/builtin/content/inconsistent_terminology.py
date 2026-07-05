"""Content inconsistent terminology rule"""

import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.content_analysis import (
    _required_literal,
    gather_all_content_blocks,
)


class ContentInconsistentTerminologyRule(Rule):
    """Detect inconsistent terminology across instruction files"""

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

    config_schema = {
        "groups": {
            "type": "dict",
            "default": {},
            "description": (
                "Per-group overrides keyed by group name (e.g. 'function/method'): "
                "'off' or false disables the group; a severity ('error', 'warning', "
                "'info') overrides the rule severity for that group"
            ),
        },
    }

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        self._group_overrides: Dict[str, Optional[Severity]] = self._parse_group_overrides()

    def _parse_group_overrides(self) -> Dict[str, Optional[Severity]]:
        """Parse the ``groups`` config into {group name: severity or None}.

        ``None`` means the group is disabled. Groups absent from the map keep
        the rule-level severity.
        """
        raw = self.config.get("groups")
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise ValueError(
                f"'groups' for rule '{self.rule_id}' must be a mapping of "
                f"group name to 'off' or a severity, got {type(raw).__name__}"
            )
        valid_names = [name for name, _ in self._TERM_GROUPS]
        overrides: Dict[str, Optional[Severity]] = {}
        for name, value in raw.items():
            if name not in valid_names:
                raise ValueError(
                    f"Unknown terminology group '{name}' for rule "
                    f"'{self.rule_id}'. Valid groups: {', '.join(valid_names)}"
                )
            # YAML may parse a bare ``off`` as boolean False depending on the
            # loader, so accept the boolean and both string spellings.
            if value is False or (isinstance(value, str) and value.lower() in ("off", "false")):
                overrides[name] = None
                continue
            try:
                overrides[name] = Severity(value.lower() if isinstance(value, str) else value)
            except (ValueError, KeyError, TypeError) as err:
                valid = ", ".join(s.value for s in Severity)
                raise ValueError(
                    f"Invalid setting '{value}' for terminology group '{name}' "
                    f"in rule '{self.rule_id}'. Valid values: off, {valid}"
                ) from err
        return overrides

    @property
    def rule_id(self) -> str:
        return "content-inconsistent-terminology"

    @property
    def description(self) -> str:
        return "Detect inconsistent terminology across instruction files (e.g., mixing 'directory' and 'folder')"

    def default_severity(self) -> Severity:
        return Severity.INFO

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        content_files = gather_all_content_blocks(context)
        if len(content_files) < self.MIN_FILES:
            return []

        violations = []
        for group_name, patterns in self._TERM_GROUPS:
            group_severity = self._group_overrides.get(group_name, self.severity)
            if group_severity is None:
                continue
            term_usage: Dict[str, int] = defaultdict(int)
            files_by_term: Dict[str, List[Path]] = defaultdict(list)
            for cf in content_files:
                body = cf.read_body()
                if not body:
                    continue
                lowered = body.lower()
                for pattern in patterns:
                    literal = _required_literal(pattern.pattern, pattern.flags)
                    if literal is not None and literal not in lowered:
                        continue
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
                    violations.append(self.violation(msg, file_path=fpath, severity=group_severity))

        return violations

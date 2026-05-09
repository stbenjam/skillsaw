"""
Rules for validating .coderabbit.yaml configuration files.

CodeRabbit config files contain ``instructions`` fields consumed by an LLM.
These rules validate the YAML structure and check the instruction text for
common content quality issues (weak/hedge language, empty instructions).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, List, Optional, Tuple

import yaml

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.rules.builtin.utils import read_text

# ---------------------------------------------------------------------------
# Weak / hedge language patterns
# ---------------------------------------------------------------------------

_WEAK_LANGUAGE_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"\bmaybe\b", re.IGNORECASE), "maybe"),
    (re.compile(r"\bperhaps\b", re.IGNORECASE), "perhaps"),
    (re.compile(r"\btry to\b", re.IGNORECASE), "try to"),
    (re.compile(r"\bmight want to\b", re.IGNORECASE), "might want to"),
    (re.compile(r"\bcould potentially\b", re.IGNORECASE), "could potentially"),
    (
        re.compile(
            r"\bconsider\s+(?:using|adding|implementing|creating|setting|enabling|disabling|replacing|switching|migrating|wrapping|converting)\b",
            re.IGNORECASE,
        ),
        "consider",
    ),
    (re.compile(r"\bif possible\b", re.IGNORECASE), "if possible"),
    (re.compile(r"\bwhen feasible\b", re.IGNORECASE), "when feasible"),
    (re.compile(r"\bit would be nice\b", re.IGNORECASE), "it would be nice"),
]

# ---------------------------------------------------------------------------
# Instruction extraction helpers
# ---------------------------------------------------------------------------

_CODERABBIT_FILENAME = ".coderabbit.yaml"


def _find_yaml_key_line(raw: str, key: str) -> Optional[int]:
    """Find the line number of a YAML key in raw text.

    Scans line-by-line for ``key:`` at any indentation level.  Returns
    the 1-based line number of the *last* occurrence so that nested keys
    such as ``instructions`` resolve to the most specific location when
    the caller is walking a particular branch of the tree.  For
    top-level unique keys the result is the same either way.
    """
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*:")
    last: Optional[int] = None
    for i, line in enumerate(raw.splitlines(), 1):
        if pattern.match(line):
            last = i
    return last


def _find_yaml_key_line_after(raw: str, key: str, after_line: int) -> Optional[int]:
    """Find the line number of a YAML key occurring after a given line."""
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*:")
    for i, line in enumerate(raw.splitlines(), 1):
        if i > after_line and pattern.match(line):
            return i
    return None


def _find_nth_key_line(raw: str, key: str, n: int) -> Optional[int]:
    """Find the line number of the *n*-th (0-based) occurrence of *key*."""
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*:")
    count = 0
    for i, line in enumerate(raw.splitlines(), 1):
        if pattern.match(line):
            if count == n:
                return i
            count += 1
    return None


def _find_nth_list_item_key_line(raw: str, key: str, n: int, after_line: int = 0) -> Optional[int]:
    """Find the *n*-th (0-based) YAML list-item key (``- key:``) after *after_line*.

    In YAML sequences the first key of each item is prefixed with ``- ``,
    e.g. ``  - name: value``.  The standard ``_find_nth_key_line`` helper
    doesn't match these because ``-`` is not whitespace.  This variant
    matches both ``- key:`` and bare ``key:`` lines.
    """
    pattern = re.compile(rf"^\s*-\s+{re.escape(key)}\s*:")
    count = 0
    for i, line in enumerate(raw.splitlines(), 1):
        if i <= after_line:
            continue
        if pattern.match(line):
            if count == n:
                return i
            count += 1
    return None


def _extract_instructions(data: Any, raw: str) -> List[Tuple[str, str, Optional[int]]]:
    """Extract all instruction text fields from a parsed CodeRabbit config.

    Returns a list of ``(location_label, text, line_number)`` tuples.
    """
    results: List[Tuple[str, str, Optional[int]]] = []
    if not isinstance(data, dict):
        return results

    # reviews.instructions
    reviews = data.get("reviews")
    if isinstance(reviews, dict):
        instr = reviews.get("instructions")
        if isinstance(instr, str) and instr.strip():
            # Find the "instructions" key that appears after "reviews"
            reviews_line = _find_yaml_key_line(raw, "reviews")
            line = None
            if reviews_line is not None:
                line = _find_yaml_key_line_after(raw, "instructions", reviews_line)
            if line is None:
                line = _find_yaml_key_line(raw, "instructions")
            results.append(("reviews.instructions", instr, line))

        # reviews.path_instructions[].instructions
        path_instructions = reviews.get("path_instructions")
        if isinstance(path_instructions, list):
            for idx, entry in enumerate(path_instructions):
                if not isinstance(entry, dict):
                    continue
                pi = entry.get("instructions")
                if isinstance(pi, str) and pi.strip():
                    path_val = entry.get("path", f"[{idx}]")
                    line = _find_nth_key_line(raw, "instructions", len(results))
                    results.append(
                        (f"reviews.path_instructions[{path_val}].instructions", pi, line)
                    )

        # reviews.tools.<tool>.instructions
        tools = reviews.get("tools")
        if isinstance(tools, dict):
            for tool_name, tool_cfg in tools.items():
                if not isinstance(tool_cfg, dict):
                    continue
                ti = tool_cfg.get("instructions")
                if isinstance(ti, str) and ti.strip():
                    tool_line = _find_yaml_key_line(raw, tool_name)
                    line = None
                    if tool_line is not None:
                        line = _find_yaml_key_line_after(raw, "instructions", tool_line)
                    results.append((f"reviews.tools.{tool_name}.instructions", ti, line))

        # reviews.pre_merge_checks.custom_checks[].instructions
        pre_merge = reviews.get("pre_merge_checks")
        if isinstance(pre_merge, dict):
            custom_checks = pre_merge.get("custom_checks")
            if isinstance(custom_checks, list):
                # Find the "custom_checks" key so we only look within it.
                custom_checks_line = _find_yaml_key_line(raw, "custom_checks") or 0
                for idx, check in enumerate(custom_checks):
                    if not isinstance(check, dict):
                        continue
                    ci = check.get("instructions")
                    if isinstance(ci, str) and ci.strip():
                        check_name = check.get("name", f"[{idx}]")
                        # Find the nth list-item "- name:" after custom_checks,
                        # then the "instructions" key following it.
                        name_line = _find_nth_list_item_key_line(
                            raw, "name", idx, after_line=custom_checks_line
                        )
                        line = None
                        if name_line is not None:
                            line = _find_yaml_key_line_after(raw, "instructions", name_line)
                        results.append(
                            (
                                f"reviews.pre_merge_checks.custom_checks[{check_name}].instructions",
                                ci,
                                line,
                            )
                        )

    # chat.instructions
    chat = data.get("chat")
    if isinstance(chat, dict):
        ci = chat.get("instructions")
        if isinstance(ci, str) and ci.strip():
            chat_line = _find_yaml_key_line(raw, "chat")
            line = None
            if chat_line is not None:
                line = _find_yaml_key_line_after(raw, "instructions", chat_line)
            if line is None:
                line = _find_yaml_key_line(raw, "instructions")
            results.append(("chat.instructions", ci, line))

    return results


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


class CoderabbitYamlValidRule(Rule):
    """Validate that .coderabbit.yaml is valid YAML"""

    repo_types = {RepositoryType.CODERABBIT}

    @property
    def rule_id(self) -> str:
        return "coderabbit-yaml-valid"

    @property
    def description(self) -> str:
        return ".coderabbit.yaml must be valid YAML"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        cr_path = context.root_path / _CODERABBIT_FILENAME

        if not cr_path.exists():
            return violations

        raw = read_text(cr_path)
        if raw is None:
            violations.append(
                self.violation(
                    f"Failed to read {_CODERABBIT_FILENAME} (invalid encoding or I/O error)",
                    file_path=cr_path,
                )
            )
            return violations

        try:
            data = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            line: Optional[int] = None
            if hasattr(exc, "problem_mark") and exc.problem_mark is not None:
                line = exc.problem_mark.line + 1  # 0-based → 1-based
            violations.append(
                self.violation(
                    f"Invalid YAML in {_CODERABBIT_FILENAME}: {exc}",
                    file_path=cr_path,
                    line=line,
                )
            )
            return violations

        if not isinstance(data, dict):
            violations.append(
                self.violation(
                    f"{_CODERABBIT_FILENAME} must be a YAML mapping at the top level",
                    file_path=cr_path,
                )
            )

        return violations


class CoderabbitInstructionsRule(Rule):
    """Check instruction text in .coderabbit.yaml for content quality issues"""

    repo_types = {RepositoryType.CODERABBIT}

    @property
    def rule_id(self) -> str:
        return "coderabbit-instructions"

    @property
    def description(self) -> str:
        return "Check .coderabbit.yaml instruction fields for content quality issues"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        cr_path = context.root_path / _CODERABBIT_FILENAME

        if not cr_path.exists():
            return violations

        raw = read_text(cr_path)
        if raw is None:
            return violations

        try:
            data = yaml.safe_load(raw)
        except yaml.YAMLError:
            # Invalid YAML is caught by CoderabbitYamlValidRule
            return violations

        if not isinstance(data, dict):
            return violations

        instructions = _extract_instructions(data, raw)

        for location, text, line in instructions:
            self._check_weak_language(cr_path, location, text, line, violations)

        return violations

    # ------------------------------------------------------------------
    # Content checks
    # ------------------------------------------------------------------

    def _check_weak_language(
        self,
        file_path: Path,
        location: str,
        text: str,
        line: Optional[int],
        violations: List[RuleViolation],
    ) -> None:
        """Flag hedge / weak language in instruction text."""
        found: List[str] = []
        for pattern, label in _WEAK_LANGUAGE_PATTERNS:
            if pattern.search(text):
                found.append(label)

        if found:
            phrases = ", ".join(f"'{p}'" for p in found[:3])
            suffix = f" (and {len(found) - 3} more)" if len(found) > 3 else ""
            violations.append(
                self.violation(
                    message=(
                        f"Weak/hedge language in {location}: {phrases}{suffix}. "
                        "Use direct, imperative language in LLM instructions."
                    ),
                    file_path=file_path,
                    line=line,
                )
            )

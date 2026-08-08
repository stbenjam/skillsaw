"""
Rule: cursor-rules-valid
"""

from collections import defaultdict
from pathlib import Path
from typing import Any, List, Optional, Tuple

from skillsaw.context import HAS_CURSOR, RepositoryContext
from skillsaw.diagnostics import safe_display
from skillsaw.rule import AutofixConfidence, AutofixResult, Rule, RuleViolation, Severity
from skillsaw.rules.builtin.content_analysis import CursorRuleBlock, InstructionBlock
from skillsaw.paths import safe_resolve
from skillsaw.rules.builtin.utils import read_text
from skillsaw.utils import replace_frontmatter_field

_ALWAYS_APPLY_FIX_PREFIX = "'alwaysApply' must be a boolean"

#: Strings YAML did not turn into a boolean but a human plainly meant as one.
#: ``alwaysApply: "true"`` is the single most common way a Cursor rule ends
#: up never applying, because the value is truthy to a human and a plain
#: string to the parser.
#: Deliberately excludes "1"/"0": those are a guess about what the author
#: meant, not a spelling of a boolean, and a SAFE fix may not infer intent.
_BOOLEAN_STRINGS = {
    "true": "true",
    "false": "false",
    "yes": "true",
    "no": "false",
    "on": "true",
    "off": "false",
}


def _as_glob_list(value: Any) -> Optional[List[str]]:
    """Normalize a ``globs`` value to a list of patterns, or ``None`` if malformed."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        if not all(isinstance(item, str) for item in value):
            return None
        return list(value)
    return None


def _has_separator_comma(pattern: str) -> bool:
    """Whether *pattern* has a comma outside brace expansion.

    ``src/**/*.{ts,tsx}`` is one pattern whose comma belongs to the brace
    group — every reading of it agrees. Only a comma at brace depth zero is
    the ambiguous "one pattern or several?" case.
    """
    depth = 0
    for char in pattern:
        if char == "{":
            depth += 1
        elif char == "}":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            return True
    return False


class CursorRulesValidRule(Rule):
    """Validate .cursor/rules/*.mdc frontmatter and the legacy .cursorrules file"""

    since = "0.19.0"

    formats = frozenset({HAS_CURSOR})

    autofix_confidence = AutofixConfidence.SAFE

    @property
    def rule_id(self) -> str:
        return "cursor-rules-valid"

    @property
    def description(self) -> str:
        return "Cursor .mdc rules must have frontmatter that lets the rule activate"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []

        root_rules_dir = safe_resolve(context.root_path / ".cursor" / "rules")
        has_root_rules = False
        for block in context.lint_tree.find(CursorRuleBlock):
            violations.extend(self._check_mdc(block))
            # Only a rules directory at the repository root displaces the
            # root .cursorrules. A nested package's .cursor/rules governs
            # that package, and says nothing about the root file.
            resolved = safe_resolve(block.path)
            if root_rules_dir is not None and resolved is not None:
                has_root_rules = has_root_rules or resolved.is_relative_to(root_rules_dir)

        violations.extend(self._check_legacy_cursorrules(context, has_root_rules))
        return violations

    def _check_mdc(self, block: CursorRuleBlock) -> List[RuleViolation]:
        """Check one .mdc rule file."""
        if block.frontmatter_error:
            # No recovery: Cursor cannot read the activation mode, so the
            # rule is skipped wholesale rather than partly applied.
            return [
                self.violation(
                    f"{block.frontmatter_error} — Cursor skips the rule entirely",
                    file_path=block.path,
                    line=block.frontmatter_error_line,
                    block=block,
                    fixable=False,
                )
            ]

        violations: List[RuleViolation] = []
        always_apply, always_violations = self._check_always_apply(block)
        violations.extend(always_violations)
        description, desc_violations = self._check_description(block)
        violations.extend(desc_violations)
        globs, glob_violations = self._check_globs(block)
        violations.extend(glob_violations)

        # Activation analysis last: it is only meaningful once each field has
        # been read successfully, and repeating it for a file that already
        # failed a type check would be noise on top of the real defect.
        if not always_violations and not desc_violations and not glob_violations:
            if not always_apply and not description and not globs:
                violations.append(
                    self.violation(
                        "Rule never activates on its own: set 'alwaysApply: true', "
                        "add 'globs' to auto-attach, or add a 'description' so the "
                        "agent can request it. Ignore this if the rule is meant to "
                        "be invoked manually with @" + block.path.stem,
                        file_path=block.path,
                        block=block,
                        severity=Severity.INFO,
                        fixable=False,
                    )
                )

        return violations

    def _check_always_apply(self, block: CursorRuleBlock) -> Tuple[bool, List[RuleViolation]]:
        """Return whether the rule is always-on, plus any type violation."""
        field = block.field("alwaysApply")
        if field is None:
            return False, []
        value = field.value
        if isinstance(value, bool):
            return value, []
        detail = (
            "a quoted value is a string, and the rule is treated as not always-applied"
            if isinstance(value, str)
            else "only true or false select the always-apply mode"
        )
        return False, [
            self.violation(
                f"{_ALWAYS_APPLY_FIX_PREFIX}, got {safe_display(repr(value))} — {detail}",
                file_path=block.path,
                line=field.field_line,
                block=block,
                # Only a recognisable boolean spelling can be repaired without
                # guessing what the author meant.
                fixable=isinstance(value, str) and value.strip().lower() in _BOOLEAN_STRINGS,
            )
        ]

    def _check_description(self, block: CursorRuleBlock) -> Tuple[str, List[RuleViolation]]:
        """Return the routing description, plus any type violation."""
        field = block.field("description")
        if field is None or field.value is None:
            return "", []
        if not isinstance(field.value, str):
            return "", [
                self.violation(
                    f"'description' must be a string, got {type(field.value).__name__}",
                    file_path=block.path,
                    line=field.field_line,
                    block=block,
                    fixable=False,
                )
            ]
        return field.value.strip(), []

    def _check_globs(self, block: CursorRuleBlock) -> Tuple[List[str], List[RuleViolation]]:
        """Return the auto-attach patterns, plus shape violations.

        Shape only: whether a pattern *matches* anything is deliberately not
        checked. Doing so costs a repository walk per pattern, and a rule
        written for files that do not exist yet is a legitimate thing to
        commit — the same reasoning ``claude-rules-valid`` applies to
        ``paths``.
        """
        field = block.field("globs")
        if field is None or field.value is None:
            return [], []

        patterns = _as_glob_list(field.value)
        if patterns is None:
            return [], [
                self.violation(
                    "'globs' must be a string or a list of strings, got "
                    f"{type(field.value).__name__}",
                    file_path=block.path,
                    line=field.field_line,
                    block=block,
                    fixable=False,
                )
            ]

        # The comma question only arises for the string form. A YAML list has
        # already said how many patterns it holds, so telling its author to
        # "write a YAML list" would prescribe the state the file is in.
        written_as_string = isinstance(field.value, str)

        violations: List[RuleViolation] = []
        kept: List[str] = []
        for index, pattern in enumerate(patterns):
            where = f"globs[{index}]" if len(patterns) > 1 else "globs"
            stripped = pattern.strip()
            if not stripped:
                violations.append(
                    self.violation(
                        f"{where}: empty glob pattern",
                        file_path=block.path,
                        line=field.field_line,
                        block=block,
                        fixable=False,
                    )
                )
                continue
            if written_as_string and _has_separator_comma(stripped):
                # Cursor documents a comma-separated string, but whether the
                # parser splits it or keeps one literal pattern has changed
                # between releases. A YAML list means the same thing under
                # every reading, so the ambiguity is the finding — not a
                # claim about which way this Cursor version jumps.
                violations.append(
                    self.violation(
                        f"{where}: {safe_display(stripped)!r} contains a comma, which "
                        "different Cursor versions read as one pattern or several — "
                        "write a YAML list instead",
                        file_path=block.path,
                        line=field.field_line,
                        block=block,
                        severity=Severity.WARNING,
                        fixable=False,
                    )
                )
            if stripped.startswith("/") or stripped.startswith("\\"):
                violations.append(
                    self.violation(
                        f"{where}: {safe_display(stripped)!r} must be repository-relative, "
                        "not absolute",
                        file_path=block.path,
                        line=field.field_line,
                        block=block,
                        fixable=False,
                    )
                )
                continue
            kept.append(stripped)

        return kept, violations

    def _check_legacy_cursorrules(
        self, context: RepositoryContext, has_root_rules: bool
    ) -> List[RuleViolation]:
        """A legacy .cursorrules is dead weight once .cursor/rules/ exists."""
        if not has_root_rules:
            return []
        legacy = context.root_path / ".cursorrules"
        for block in context.lint_tree.find(InstructionBlock):
            if block.path != legacy:
                continue
            return [
                self.violation(
                    ".cursorrules is deprecated and its precedence against "
                    ".cursor/rules/ is undefined — move its content into a .mdc "
                    "rule or AGENTS.md so what the agent reads is unambiguous",
                    file_path=block.path,
                    severity=Severity.WARNING,
                    fixable=False,
                )
            ]
        return []

    def fix(
        self, context: RepositoryContext, violations: List[RuleViolation]
    ) -> List[AutofixResult]:
        by_file: defaultdict[Path, List[RuleViolation]] = defaultdict(list)
        for violation in violations:
            if violation.file_path and violation.message.startswith(_ALWAYS_APPLY_FIX_PREFIX):
                by_file[violation.file_path].append(violation)

        results: List[AutofixResult] = []
        for file_path, file_violations in by_file.items():
            original = read_text(file_path)
            if original is None:
                continue
            fixed = self._fix_always_apply(file_path, original)
            if fixed is None or fixed == original:
                continue
            results.append(
                AutofixResult(
                    rule_id=self.rule_id,
                    file_path=file_path,
                    confidence=AutofixConfidence.SAFE,
                    original_content=original,
                    fixed_content=fixed,
                    description="Converted quoted 'alwaysApply' value to a YAML boolean",
                    violations_fixed=file_violations,
                )
            )
        return results

    def _fix_always_apply(self, file_path: Path, original: str) -> Optional[str]:
        """Rewrite a boolean-looking string ``alwaysApply`` as a real boolean.

        Re-reads the value from the file rather than parsing it back out of
        the violation message, so the fix can never act on a spelling
        ``check()`` did not actually see.
        """
        block = CursorRuleBlock(path=file_path)
        field = block.field("alwaysApply")
        if field is None or not isinstance(field.value, str):
            return None
        boolean = _BOOLEAN_STRINGS.get(field.value.strip().lower())
        if boolean is None:
            return None
        return replace_frontmatter_field(original, "alwaysApply", f"alwaysApply: {boolean}")

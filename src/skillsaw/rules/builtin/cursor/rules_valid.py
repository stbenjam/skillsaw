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


def _split_patterns(value: str) -> List[str]:
    """Split Cursor's documented comma-separated ``globs`` scalar.

    Cursor's docs say "separate multiple patterns with commas", so the scalar
    form is a list, and each component has to be checked on its own — a
    ``globs`` of ``", "`` is one non-empty string but no usable pattern.
    Commas inside a brace alternation (``src/{a,b}/**``) belong to the
    pattern, so only depth-zero commas separate.
    """
    parts: List[str] = []
    current: List[str] = []
    depth = 0
    for char in value:
        if char == "{":
            depth += 1
        elif char == "}":
            depth = max(depth - 1, 0)
        if char == "," and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    parts.append("".join(current))
    return parts


def _as_glob_list(value: Any) -> Optional[List[str]]:
    """Normalize a ``globs`` value to a list of patterns, or ``None`` if malformed."""
    if isinstance(value, str):
        return _split_patterns(value)
    if isinstance(value, list):
        if not all(isinstance(item, str) for item in value):
            return None
        return list(value)
    return None


def _cursor_workspace(mdc_path: Path) -> Optional[Path]:
    """The directory a ``.cursor/rules/**.mdc`` file's workspace root.

    Cursor resolves both `.cursorrules` and `.cursor/` from the directory
    opened as the workspace, so the two only compete when they share one.
    """
    for parent in mdc_path.parents:
        if parent.name == ".cursor":
            return safe_resolve(parent.parent)
    return None


def _replace_key_line(original: str, line: Optional[int], replacement: str) -> Optional[str]:
    """Replace one 1-based line, keeping the file's line count and endings.

    Refuses unless the line really does declare the key the replacement
    declares, so a stale or wrong line number can never rewrite something
    else. Line-scoped by construction: no search, no ``str.replace``.
    """
    if line is None or line < 1:
        return None
    lines = original.split("\n")
    if line > len(lines):
        return None
    key = replacement.split(":", 1)[0].strip()
    target = lines[line - 1]
    # ``"alwaysApply": true`` declares the same key as ``alwaysApply: true``;
    # YAML allows the quotes and Cursor's reader tolerates them.
    declared = target.split(":", 1)[0].strip().strip("\"'")
    if declared != key:
        return None
    # Preserve a CRLF ending: splitting on "\n" leaves the "\r" on the line.
    suffix = "\r" if target.endswith("\r") else ""
    # Preserve the line's own indentation: a uniformly indented top-level
    # mapping is valid YAML, and rewriting one key at column zero leaves the
    # siblings indented under a scalar — invalid to the strict parser and
    # invisible to the lenient one, which reads keys at column zero only.
    indent = target[: len(target) - len(target.lstrip())]
    lines[line - 1] = indent + replacement + _trailing_comment(target) + suffix
    return "\n".join(lines)


def _trailing_comment(line: str) -> str:
    """The ``# ...`` suffix of *line*, with the spacing before it, or ``""``.

    Only the scalar needs rewriting, so an authored note beside it survives —
    replacing the whole line would silently delete it on every fix. A ``#``
    inside quotes is part of the value, not a comment, so the scan tracks
    quoting rather than taking the first ``#`` it sees.
    """
    body = line.rstrip("\r")
    quote = ""
    for index, char in enumerate(body):
        if quote:
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
        elif char == "#" and index > 0 and body[index - 1] in " \t":
            before = body[:index]
            return before[len(before.rstrip()) :] + body[index:]
    return ""


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

        # Which workspaces hold modern rules. A package's .cursor/rules
        # governs that package and says nothing about the root file, so the
        # legacy check pairs each .cursorrules with rules from its *own*
        # enclosing directory rather than the repository root's.
        rules_workspaces = set()
        for block in context.lint_tree.find(CursorRuleBlock):
            violations.extend(self._check_mdc(block))
            workspace = _cursor_workspace(block.path)
            if workspace is not None:
                rules_workspaces.add(workspace)

        violations.extend(self._check_legacy_cursorrules(context, rules_workspaces))
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
                # Fixability is derived from the repair itself, never
                # guessed alongside it: an independent predicate can
                # advertise fixes the repair then declines. When the
                # predicate *is* the repair, they cannot diverge.
                fixable=self._repair_always_apply(block.path) is not None,
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
            # A Windows drive letter is absolute wherever skillsaw runs —
            # the repository it cannot match is the same either way, so this
            # must not depend on the linting host's OS.
            drive_absolute = len(stripped) > 2 and stripped[0].isalpha() and stripped[1] == ":"
            if stripped.startswith("/") or stripped.startswith("\\") or drive_absolute:
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
        self, context: RepositoryContext, rules_workspaces: set
    ) -> List[RuleViolation]:
        """A legacy .cursorrules is dead weight beside a sibling .cursor/rules/.

        Per workspace, not per repository: opening ``apps/web`` in Cursor
        shows it that package's ``.cursorrules`` and its ``.cursor/rules/``
        together, which is the same ambiguity the root pair has.
        """
        violations: List[RuleViolation] = []
        for block in context.lint_tree.find(InstructionBlock):
            if block.path.name != ".cursorrules":
                continue
            workspace = safe_resolve(block.path.parent)
            if workspace is None or workspace not in rules_workspaces:
                continue
            violations.append(
                self.violation(
                    ".cursorrules is deprecated and its precedence against "
                    ".cursor/rules/ is undefined — move its content into a .mdc "
                    "rule or AGENTS.md so what the agent reads is unambiguous",
                    file_path=block.path,
                    severity=Severity.WARNING,
                    fixable=False,
                )
            )
        return violations

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
            fixed = self._repair_always_apply(file_path)
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

    def _repair_always_apply(self, file_path: Path) -> Optional[str]:
        """The repaired file content, or ``None`` when no repair is possible.

        Reads the value from the file rather than parsing it back out of the
        violation message, so a fix can never act on a spelling ``check()``
        did not see. The single source of truth for "is this fixable": ``check()`` asks
        it to set ``fixable`` and ``fix()`` asks it for the content, so the
        answer cannot differ between them.
        """
        original = read_text(file_path)
        if original is None:
            return None
        block = CursorRuleBlock(path=file_path)
        field = block.field("alwaysApply")
        if field is None or not isinstance(field.value, str):
            return None
        # A newline in the value marks a block scalar — declined early;
        # the line-count invariant below explains why no rewrite is correct.
        if "\n" in field.value:
            return None
        boolean = _BOOLEAN_STRINGS.get(field.value.strip().lower())
        if boolean is None:
            return None
        # The line-scoped rewrite is preferred, not a fallback: it touches
        # exactly the span that is wrong, so the line count holds and an
        # authored trailing comment survives. ``replace_frontmatter_field``
        # re-emits the whole field and drops both. It stays for the case
        # where no line number was recovered.
        candidate = _replace_key_line(original, field.field_line, f"alwaysApply: {boolean}")
        if candidate is None:
            candidate = replace_frontmatter_field(
                original, "alwaysApply", f"alwaysApply: {boolean}"
            )
        if candidate is None or candidate == original:
            return None
        # A value wider than its key line — a folded or literal block scalar,
        # ``alwaysApply: >`` with an indented ``true`` — has a span the
        # one-line replacement cannot fill, so rewriting it deletes the
        # continuation and shifts every later diagnostic. Decline instead of
        # corrupting; check() asks this same function, so the violation stops
        # advertising a fix at the same moment. Stated as the line-count
        # invariant rather than as a block-scalar test, so any other
        # multi-line spelling is refused too.
        if candidate.count("\n") != original.count("\n"):
            return None
        return candidate

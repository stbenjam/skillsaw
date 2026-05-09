"""
Deep AGENTS.md validation rules.

Covers size limits, override semantics, hierarchy consistency,
dead references, weak language, structure quality, and more.
"""

import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from skillsaw.context import RepositoryContext
from skillsaw.rule import AutofixConfidence, AutofixResult, Rule, RuleViolation, Severity
from skillsaw.rules.builtin.utils import read_text

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)", re.MULTILINE)

_AGENTS_MD = "AGENTS.md"
_OVERRIDE_MD = "AGENTS.override.md"

# ── helpers ──────────────────────────────────────────────────────────────────


def _find_agents_files(root: Path) -> List[Path]:
    """Find all AGENTS.md files in the repo (root + subdirs), skipping hidden dirs."""
    results = []
    root_file = root / _AGENTS_MD
    if root_file.exists():
        results.append(root_file)
    try:
        for child in sorted(root.rglob(_AGENTS_MD)):
            if child == root_file:
                continue
            rel = child.relative_to(root.resolve())
            if any(part.startswith(".") for part in rel.parts[:-1]):
                continue
            results.append(child)
    except OSError:
        pass
    return results


def _get_sections(content: str) -> List[Tuple[str, int, str]]:
    """Return (heading_text, start_line, section_body) for each heading."""
    lines = content.splitlines()
    sections: List[Tuple[str, int, str]] = []
    heading_positions: List[Tuple[str, int]] = []
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if m:
            heading_positions.append((m.group(2).strip(), i + 1))

    for idx, (heading, start) in enumerate(heading_positions):
        if idx + 1 < len(heading_positions):
            end = heading_positions[idx + 1][1] - 1
        else:
            end = len(lines)
        body = "\n".join(lines[start:end])
        sections.append((heading, start, body))

    return sections


def _read_agents_md(context: RepositoryContext) -> Optional[Tuple[Path, str]]:
    """Read root AGENTS.md, return (path, content) or None."""
    fp = context.root_path / _AGENTS_MD
    if not fp.exists():
        return None
    content = read_text(fp)
    if content is None or not content.strip():
        return None
    return fp, content


# ── backtick path extraction ─────────────────────────────────────────────────

_BACKTICK_PATH_RE = re.compile(
    r"`([a-zA-Z0-9_.][a-zA-Z0-9_./\-]*(?:\.[a-zA-Z0-9]+)+)`" r"|`((?:\./|\.\./)[\w./\-]+)`"
)

_MARKDOWN_LINK_RE = re.compile(r"\[.*?\]\((\./[^)]+|\.\.\/[^)]+)\)")

_IGNORED_EXTENSIONS = {
    ".com",
    ".org",
    ".net",
    ".io",
    ".dev",
    ".app",
    ".ai",
    ".md",
}

_LOOKS_LIKE_URL = re.compile(r"^https?://", re.IGNORECASE)


def _extract_file_refs(content: str) -> List[Tuple[str, int]]:
    """Extract file path references with line numbers from markdown content."""
    refs: List[Tuple[str, int]] = []
    for lineno, line in enumerate(content.splitlines(), 1):
        if _LOOKS_LIKE_URL.search(line):
            clean = re.sub(r"https?://\S+", "", line)
        else:
            clean = line

        for m in _BACKTICK_PATH_RE.finditer(clean):
            path = m.group(1) or m.group(2)
            if path:
                ext = os.path.splitext(path)[1].lower()
                if ext not in _IGNORED_EXTENSIONS and "/" in path:
                    refs.append((path, lineno))

        for m in _MARKDOWN_LINK_RE.finditer(clean):
            refs.append((m.group(1), lineno))

    return refs


# ── npm / makefile command extraction ────────────────────────────────────────

_NPM_SCRIPT_RE = re.compile(r"`npm\s+run\s+([\w:.\-]+)`")
_MAKE_TARGET_RE = re.compile(r"`make\s+([\w.\-]+)`")


def _extract_command_refs(content: str) -> List[Tuple[str, str, int]]:
    """Extract (type, name, line) for npm scripts and make targets."""
    refs: List[Tuple[str, str, int]] = []
    for lineno, line in enumerate(content.splitlines(), 1):
        for m in _NPM_SCRIPT_RE.finditer(line):
            refs.append(("npm", m.group(1), lineno))
        for m in _MAKE_TARGET_RE.finditer(line):
            refs.append(("make", m.group(1), lineno))
    return refs


def _get_npm_scripts(root: Path) -> Set[str]:
    """Read script names from package.json."""
    pkg = root / "package.json"
    if not pkg.exists():
        return set()
    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
        return set(data.get("scripts", {}).keys())
    except (json.JSONDecodeError, IOError):
        return set()


def _get_make_targets(root: Path) -> Set[str]:
    """Extract target names from Makefile."""
    makefile = root / "Makefile"
    if not makefile.exists():
        return set()
    targets: Set[str] = set()
    try:
        for line in makefile.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^([\w.\-]+)\s*:", line)
            if m:
                targets.add(m.group(1))
    except (IOError, UnicodeDecodeError):
        pass
    return targets


# ── weak / vague language patterns ───────────────────────────────────────────

_WEAK_PATTERNS = [
    (re.compile(r"\bbe careful\b", re.I), "be careful"),
    (re.compile(r"\bwhere possible\b", re.I), "where possible"),
    (re.compile(r"\bas needed\b", re.I), "as needed"),
    (re.compile(r"\bgracefully\b", re.I), "gracefully"),
    (re.compile(r"\bwhen appropriate\b", re.I), "when appropriate"),
    (re.compile(r"\btry to\b", re.I), "try to"),
    (re.compile(r"\bconsider\b", re.I), "consider"),
    (re.compile(r"\bif possible\b", re.I), "if possible"),
    (re.compile(r"\bideally\b", re.I), "ideally"),
    (re.compile(r"\bclean code\b", re.I), "clean code"),
    (re.compile(r"\bbest practices\b", re.I), "best practices"),
    (re.compile(r"\bwell-structured\b", re.I), "well-structured"),
]

# ── tautological instructions ────────────────────────────────────────────────

_TAUTOLOGICAL_RE = re.compile(
    r"^\s*[-*]?\s*"
    r"(?:write clean code|be helpful|follow best practices|write good tests"
    r"|ensure code quality|maintain readability|keep it simple"
    r"|use meaningful names|write readable code|produce high-quality code"
    r"|follow coding standards|write maintainable code)\s*\.?\s*$",
    re.I | re.MULTILINE,
)

# ── negative-only pattern ────────────────────────────────────────────────────

_NEGATIVE_RE = re.compile(
    r"^[^#]*\b(?:never|don'?t|do not|avoid)\s+(?:use|do|call|import|run|write)\b",
    re.I | re.MULTILINE,
)
_POSITIVE_FOLLOW = re.compile(r"\b(?:instead|prefer|replace with)\b", re.I)

# ── hook candidate patterns ─────────────────────────────────────────────────

_HOOK_PATTERNS = [
    (re.compile(r"\balways run\b.*\bafter\b", re.I), "always run X after Y"),
    (re.compile(r"\bformat\b.*\bbefore committing\b", re.I), "format before committing"),
    (re.compile(r"\bnever push without\b.*\btests?\b", re.I), "never push without tests"),
    (re.compile(r"\brun\b.*\blint\b.*\bbefore\b", re.I), "run lint before"),
    (re.compile(r"\bbefore every commit\b", re.I), "before every commit"),
    (re.compile(r"\bpre-commit\b", re.I), "pre-commit"),
    (re.compile(r"\bafter every\b.*\b(?:push|pull|merge)\b", re.I), "after every push/pull/merge"),
]


# ═══════════════════════════════════════════════════════════════════════════════
# Rules
# ═══════════════════════════════════════════════════════════════════════════════


class AgentsMdSizeLimitRule(Rule):
    """Codex enforces a 32 KB limit on AGENTS.md. Warn at 24 KB, error at 32 KB."""

    config_schema = {
        "warn_bytes": {"type": "integer", "default": 24576, "description": "Byte count to warn at"},
        "error_bytes": {
            "type": "integer",
            "default": 32768,
            "description": "Byte count to error at",
        },
    }

    @property
    def rule_id(self) -> str:
        return "agents-md-size-limit"

    @property
    def description(self) -> str:
        return "AGENTS.md must not exceed the Codex 32 KB size limit"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        fp = context.root_path / _AGENTS_MD
        if not fp.exists():
            return []
        content = read_text(fp)
        if content is None:
            return []
        size = len(content.encode("utf-8"))
        warn_bytes = self.config.get("warn_bytes", 24576)
        error_bytes = self.config.get("error_bytes", 32768)
        if size >= error_bytes:
            return [
                self.violation(
                    f"AGENTS.md is {size:,} bytes — exceeds Codex 32 KB limit ({error_bytes:,} bytes)",
                    file_path=fp,
                    severity=Severity.ERROR,
                )
            ]
        if size >= warn_bytes:
            return [
                self.violation(
                    f"AGENTS.md is {size:,} bytes — approaching Codex 32 KB limit",
                    file_path=fp,
                )
            ]
        return []


class AgentsMdOverrideSemanticsRule(Rule):
    """Warn when AGENTS.override.md exists — it replaces, not supplements, AGENTS.md."""

    @property
    def rule_id(self) -> str:
        return "agents-md-override-semantics"

    @property
    def description(self) -> str:
        return "AGENTS.override.md replaces AGENTS.md entirely — verify it is self-contained"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        override_fp = context.root_path / _OVERRIDE_MD
        if not override_fp.exists():
            return []
        violations = [
            self.violation(
                "AGENTS.override.md exists — it REPLACES AGENTS.md entirely (not additive). "
                "Ensure it is self-contained.",
                file_path=override_fp,
            )
        ]
        agents_fp = context.root_path / _AGENTS_MD
        if agents_fp.exists():
            override_content = read_text(override_fp)
            agents_content = read_text(agents_fp)
            if override_content and agents_content:
                agents_headings = set(
                    m.group(2).strip() for m in _HEADING_RE.finditer(agents_content)
                )
                for m in re.finditer(
                    r"(?:see|refer to|as (?:described|defined) in)\s+AGENTS\.md",
                    override_content,
                    re.I,
                ):
                    line = override_content[: m.start()].count("\n") + 1
                    violations.append(
                        self.violation(
                            "AGENTS.override.md references AGENTS.md — "
                            "but override replaces it, so the reference is broken",
                            file_path=override_fp,
                            line=line,
                        )
                    )
        return violations


class AgentsMdHierarchyConsistencyRule(Rule):
    """Check subdirectory AGENTS.md files for contradictions with root."""

    @property
    def rule_id(self) -> str:
        return "agents-md-hierarchy-consistency"

    @property
    def description(self) -> str:
        return "Subdirectory AGENTS.md files should not contradict root AGENTS.md"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        root_fp = context.root_path / _AGENTS_MD
        if not root_fp.exists():
            return []
        root_content = read_text(root_fp)
        if not root_content:
            return []

        root_directives = self._extract_directives(root_content)
        if not root_directives:
            return []

        violations: List[RuleViolation] = []
        all_files = _find_agents_files(context.root_path)
        for fp in all_files:
            if fp == root_fp:
                continue
            content = read_text(fp)
            if not content:
                continue
            sub_directives = self._extract_directives(content)
            for key, (sub_val, sub_line) in sub_directives.items():
                if key in root_directives:
                    root_val, _ = root_directives[key]
                    if root_val.lower() != sub_val.lower():
                        violations.append(
                            self.violation(
                                f"Contradicts root AGENTS.md: "
                                f'root says "{root_val}" but this file says "{sub_val}" for "{key}"',
                                file_path=fp,
                                line=sub_line,
                            )
                        )
        return violations

    @staticmethod
    def _extract_directives(content: str) -> Dict[str, Tuple[str, int]]:
        """Extract 'use X' / 'prefer X' directives with line numbers.

        Returns dict mapping verb -> (argument, line). When the same verb
        appears multiple times, only the last occurrence is kept (the
        comparison cares about differing arguments, not count).
        """
        directives: Dict[str, Tuple[str, int]] = {}
        pattern = re.compile(
            r"^\s*[-*]?\s*(use|prefer|always use|require)\s+(\S+)",
            re.I | re.MULTILINE,
        )
        for m in pattern.finditer(content):
            line = content[: m.start()].count("\n") + 1
            verb = m.group(1).strip().lower()
            arg = m.group(2).strip().lower().rstrip(".,;:")
            directives[verb] = (arg, line)
        return directives


class AgentsMdDeadFileRefsRule(Rule):
    """Scan for file paths referenced in AGENTS.md and verify they exist."""

    @property
    def rule_id(self) -> str:
        return "agents-md-dead-file-refs"

    @property
    def description(self) -> str:
        return "File paths referenced in AGENTS.md should exist in the repo"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        result = _read_agents_md(context)
        if not result:
            return []
        fp, content = result
        violations: List[RuleViolation] = []
        refs = _extract_file_refs(content)
        for path_str, lineno in refs:
            target = (context.root_path / path_str).resolve()
            try:
                target.relative_to(context.root_path.resolve())
            except ValueError:
                continue
            if not target.exists():
                violations.append(
                    self.violation(
                        f"Referenced path does not exist: {path_str}",
                        file_path=fp,
                        line=lineno,
                    )
                )
        return violations


class AgentsMdDeadCommandRefsRule(Rule):
    """Scan for npm scripts and make targets referenced in AGENTS.md and verify they exist."""

    @property
    def rule_id(self) -> str:
        return "agents-md-dead-command-refs"

    @property
    def description(self) -> str:
        return "Shell commands in AGENTS.md (npm scripts, make targets) should exist in the project"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        result = _read_agents_md(context)
        if not result:
            return []
        fp, content = result
        violations: List[RuleViolation] = []
        refs = _extract_command_refs(content)
        if not refs:
            return []

        npm_scripts = _get_npm_scripts(context.root_path)
        make_targets = _get_make_targets(context.root_path)

        for cmd_type, name, lineno in refs:
            if cmd_type == "npm" and npm_scripts and name not in npm_scripts:
                violations.append(
                    self.violation(
                        f'npm script "{name}" not found in package.json',
                        file_path=fp,
                        line=lineno,
                    )
                )
            elif cmd_type == "make" and make_targets and name not in make_targets:
                violations.append(
                    self.violation(
                        f'Makefile target "{name}" not found',
                        file_path=fp,
                        line=lineno,
                    )
                )
        return violations


class AgentsMdWeakLanguageRule(Rule):
    """Detect vague/weak language that agents tend to ignore."""

    @property
    def rule_id(self) -> str:
        return "agents-md-weak-language"

    @property
    def description(self) -> str:
        return "AGENTS.md should use direct, actionable language instead of vague phrases"

    def default_severity(self) -> Severity:
        return Severity.INFO

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        result = _read_agents_md(context)
        if not result:
            return []
        fp, content = result
        violations: List[RuleViolation] = []
        seen: Set[str] = set()
        for lineno, line in enumerate(content.splitlines(), 1):
            for pattern, phrase in _WEAK_PATTERNS:
                if pattern.search(line) and phrase not in seen:
                    seen.add(phrase)
                    violations.append(
                        self.violation(
                            f'Weak/vague language: "{phrase}" — '
                            "rewrite as a concrete, actionable directive",
                            file_path=fp,
                            line=lineno,
                        )
                    )
        return violations

    def fix(
        self, context: RepositoryContext, violations: List[RuleViolation]
    ) -> List[AutofixResult]:
        result = _read_agents_md(context)
        if not result:
            return []
        fp, content = result
        suggestions: List[str] = []
        for v in violations:
            suggestions.append(f"Line {v.line}: {v.message}")
        if not suggestions:
            return []
        return [
            AutofixResult(
                rule_id=self.rule_id,
                file_path=fp,
                confidence=AutofixConfidence.SUGGEST,
                original_content=content,
                fixed_content=content,
                description="Weak language found — review and rewrite:\n" + "\n".join(suggestions),
                violations_fixed=violations,
            )
        ]


class AgentsMdNegativeOnlyRule(Rule):
    """Detect 'never use X' without a positive alternative."""

    @property
    def rule_id(self) -> str:
        return "agents-md-negative-only"

    @property
    def description(self) -> str:
        return "Negative instructions (never/don't) should include a positive alternative"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        result = _read_agents_md(context)
        if not result:
            return []
        fp, content = result
        violations: List[RuleViolation] = []
        for lineno, line in enumerate(content.splitlines(), 1):
            if _NEGATIVE_RE.match(line) and not _POSITIVE_FOLLOW.search(line):
                violations.append(
                    self.violation(
                        f"Negative-only instruction without alternative — "
                        f'add "use Y instead" or similar',
                        file_path=fp,
                        line=lineno,
                    )
                )
        return violations


class AgentsMdSectionLengthRule(Rule):
    """Warn when any section exceeds 50 lines (lost-in-the-middle effect)."""

    config_schema = {
        "max_lines": {"type": "integer", "default": 50, "description": "Max lines per section"},
    }

    @property
    def rule_id(self) -> str:
        return "agents-md-section-length"

    @property
    def description(self) -> str:
        return "AGENTS.md sections should not exceed 50 lines (lost-in-the-middle effect)"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        result = _read_agents_md(context)
        if not result:
            return []
        fp, content = result
        max_lines = self.config.get("max_lines", 50)
        violations: List[RuleViolation] = []
        sections = _get_sections(content)
        for heading, start_line, body in sections:
            line_count = body.count("\n") + 1
            if line_count > max_lines:
                violations.append(
                    self.violation(
                        f'Section "{heading}" is {line_count} lines (max {max_lines}) — '
                        "break into subsections to avoid lost-in-the-middle effect",
                        file_path=fp,
                        line=start_line,
                    )
                )
        return violations


class AgentsMdStructureDeepRule(Rule):
    """Enhanced structure check: task-organized sections, boundary sections, quality scoring."""

    @property
    def rule_id(self) -> str:
        return "agents-md-structure-deep"

    @property
    def description(self) -> str:
        return "AGENTS.md should have task-organized structure with boundary sections"

    def default_severity(self) -> Severity:
        return Severity.INFO

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        result = _read_agents_md(context)
        if not result:
            return []
        fp, content = result
        violations: List[RuleViolation] = []

        headings = [m.group(2).strip() for m in _HEADING_RE.finditer(content)]
        if not headings:
            return []

        when_headings = [h for h in headings if h.lower().startswith("when")]
        boundary_keywords = {"always", "ask first", "never", "do not", "don't"}
        boundary_headings = [
            h for h in headings if any(kw in h.lower() for kw in boundary_keywords)
        ]

        if len(headings) >= 3 and not when_headings:
            violations.append(
                self.violation(
                    'No task-organized sections found — consider using "When..." headings '
                    '(e.g., "When writing tests", "When reviewing PRs")',
                    file_path=fp,
                )
            )

        if len(headings) >= 3 and not boundary_headings:
            violations.append(
                self.violation(
                    "No boundary sections found — consider adding Always/Never/Ask-first sections "
                    "to define hard constraints",
                    file_path=fp,
                )
            )

        return violations

    def fix(
        self, context: RepositoryContext, violations: List[RuleViolation]
    ) -> List[AutofixResult]:
        result = _read_agents_md(context)
        if not result:
            return []
        fp, content = result
        suggestions: List[str] = []
        for v in violations:
            suggestions.append(v.message)
        if not suggestions:
            return []
        return [
            AutofixResult(
                rule_id=self.rule_id,
                file_path=fp,
                confidence=AutofixConfidence.SUGGEST,
                original_content=content,
                fixed_content=content,
                description="Structural improvements suggested:\n" + "\n".join(suggestions),
                violations_fixed=violations,
            )
        ]


class AgentsMdTautologicalRule(Rule):
    """Detect self-evident instructions that waste instruction budget."""

    @property
    def rule_id(self) -> str:
        return "agents-md-tautological"

    @property
    def description(self) -> str:
        return (
            "Remove self-evident instructions like 'write clean code' that waste instruction budget"
        )

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        result = _read_agents_md(context)
        if not result:
            return []
        fp, content = result
        violations: List[RuleViolation] = []
        for m in _TAUTOLOGICAL_RE.finditer(content):
            line = content[: m.start()].count("\n") + 1
            text = m.group(0).strip().rstrip(".")
            text = re.sub(r"^[-*]\s*", "", text)
            violations.append(
                self.violation(
                    f'Tautological instruction: "{text}" — '
                    "this is self-evident and wastes instruction budget; remove it",
                    file_path=fp,
                    line=line,
                )
            )
        return violations

    def fix(
        self, context: RepositoryContext, violations: List[RuleViolation]
    ) -> List[AutofixResult]:
        result = _read_agents_md(context)
        if not result:
            return []
        fp, content = result
        fixed = _TAUTOLOGICAL_RE.sub("", content)
        # clean up doubled blank lines left by removal
        fixed = re.sub(r"\n{3,}", "\n\n", fixed)
        if fixed == content:
            return []
        return [
            AutofixResult(
                rule_id=self.rule_id,
                file_path=fp,
                confidence=AutofixConfidence.SAFE,
                original_content=content,
                fixed_content=fixed,
                description="Removed tautological instructions",
                violations_fixed=violations,
            )
        ]


class AgentsMdCriticalPositionRule(Rule):
    """Critical instructions (MUST, NEVER, ALWAYS) should be in primacy/recency zones."""

    config_schema = {
        "zone_pct": {
            "type": "integer",
            "default": 20,
            "description": "Percentage of file considered primacy/recency zone",
        },
    }

    @property
    def rule_id(self) -> str:
        return "agents-md-critical-position"

    @property
    def description(self) -> str:
        return "Critical instructions (MUST/NEVER/ALWAYS) should be in the first or last 20% of the file"

    def default_severity(self) -> Severity:
        return Severity.INFO

    _CRITICAL_RE = re.compile(r"\b(IMPORTANT|MUST|NEVER|ALWAYS|CRITICAL)\b")

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        result = _read_agents_md(context)
        if not result:
            return []
        fp, content = result
        lines = content.splitlines()
        total = len(lines)
        if total < 10:
            return []
        zone_pct = self.config.get("zone_pct", 20)
        zone = max(2, total * zone_pct // 100)
        primacy_end = zone
        recency_start = total - zone

        violations: List[RuleViolation] = []
        for lineno, line in enumerate(lines, 1):
            if self._CRITICAL_RE.search(line):
                if primacy_end < lineno <= recency_start:
                    keyword = self._CRITICAL_RE.search(line).group(1)
                    violations.append(
                        self.violation(
                            f'"{keyword}" instruction is buried in the middle of the file '
                            f"(line {lineno}/{total}) — move to first or last {zone_pct}% for visibility",
                            file_path=fp,
                            line=lineno,
                        )
                    )
        return violations

    def fix(
        self, context: RepositoryContext, violations: List[RuleViolation]
    ) -> List[AutofixResult]:
        if not violations:
            return []
        result = _read_agents_md(context)
        if not result:
            return []
        fp, content = result
        suggestions = [f"Line {v.line}: {v.message}" for v in violations]
        return [
            AutofixResult(
                rule_id=self.rule_id,
                file_path=fp,
                confidence=AutofixConfidence.SUGGEST,
                original_content=content,
                fixed_content=content,
                description="Move critical instructions to file edges:\n" + "\n".join(suggestions),
                violations_fixed=violations,
            )
        ]


class AgentsMdHookCandidateRule(Rule):
    """Detect deterministic rules that should be hooks/automation, not instructions."""

    @property
    def rule_id(self) -> str:
        return "agents-md-hook-candidate"

    @property
    def description(self) -> str:
        return "Deterministic rules in AGENTS.md should be implemented as hooks instead"

    def default_severity(self) -> Severity:
        return Severity.INFO

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        result = _read_agents_md(context)
        if not result:
            return []
        fp, content = result
        violations: List[RuleViolation] = []
        seen: Set[str] = set()
        for lineno, line in enumerate(content.splitlines(), 1):
            for pattern, desc in _HOOK_PATTERNS:
                if pattern.search(line) and desc not in seen:
                    seen.add(desc)
                    violations.append(
                        self.violation(
                            f'Deterministic rule "{desc}" would be more reliable as a hook or '
                            "CI check than as a prose instruction",
                            file_path=fp,
                            line=lineno,
                        )
                    )
        return violations

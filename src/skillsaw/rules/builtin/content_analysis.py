"""
Shared content analyzers for instruction file intelligence rules.

These analyzers are called by content-* rules to detect quality issues
in instruction files across all formats (CLAUDE.md, AGENTS.md, GEMINI.md,
.cursorrules, copilot-instructions.md, .cursor/rules/*.mdc).
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Set

from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.utils import read_text, parse_frontmatter

_FENCED_CODE_RE = re.compile(r"^(`{3,}|~{3,}).*\n(?:.*\n)*?\1\s*$", re.MULTILINE)


def _strip_fenced_code_blocks(text: str) -> str:
    """Replace content inside fenced code blocks with blank lines to preserve line numbers."""

    def _blank_lines(m: re.Match) -> str:
        return "\n" * m.group().count("\n")

    return _FENCED_CODE_RE.sub(_blank_lines, text)


@dataclass
class WeakLanguageMatch:
    line: int
    phrase: str
    category: str
    suggested_fix: str


@dataclass
class DeadReference:
    line: int
    reference: str
    expected_path: str
    exists: bool


@dataclass
class TautologicalMatch:
    line: int
    phrase: str
    reason: str


@dataclass
class PositionIssue:
    line: int
    keyword: str
    position_score: float
    suggested_position: str


@dataclass
class RedundancyMatch:
    line: int
    instruction: str
    existing_config_file: str
    config_value: str


@dataclass
class InstructionBudget:
    total_count: int
    files_counted: List[Path]
    budget_remaining: int
    over_budget: bool


# --- Patterns ---

_HEDGING = [
    (r"\btry to\b", "Remove 'try to' — state the action directly"),
    (
        r"\bconsider\s+(?:using|adding|implementing|creating|moving|switching|enabling)\b",
        "Replace 'consider X' with 'do X' or remove",
    ),
    (r"\bif possible\b", "Remove 'if possible' — state conditions explicitly"),
    (r"\bideally\b", "Remove 'ideally' — state the requirement or drop it"),
    (r"\bwhere possible\b", "Remove 'where possible' — be specific about when"),
    (r"\bwhen appropriate\b", "Replace 'when appropriate' with specific conditions"),
    (r"\bas needed\b", "Replace 'as needed' with specific triggers"),
    (r"\byou might want to\b", "Remove 'you might want to' — state the action directly"),
    (r"\byou should probably\b", "Remove 'you should probably' — state the requirement"),
    (r"\bit would be good to\b", "Remove 'it would be good to' — state the action directly"),
    (r"\byou may want to\b", "Remove 'you may want to' — state the action directly"),
    (r"\bperhaps\b", "Remove 'perhaps' — state the recommendation or drop it"),
]

_VAGUENESS = [
    (r"\bbe careful\b", "Replace 'be careful' with specific checks to perform"),
    (r"\bgracefully\b", "Replace 'gracefully' with specific error handling behavior"),
    (r"\bproperly\b", "Remove 'properly' — describe what correct behavior looks like"),
    (r"\bcorrectly\b", "Remove 'correctly' — describe what correct behavior looks like"),
    (r"\bappropriately\b", "Remove 'appropriately' — be specific about what to do"),
]

_TAUTOLOGICAL_PHRASES = [
    (r"\bwrite clean code\b", "Models already aim for clean code — this wastes instruction budget"),
    (r"\bwrite readable code\b", "Models already aim for readable code"),
    (r"\bwrite maintainable code\b", "Models already aim for maintainable code"),
    (
        r"\bfollow the project conventions\b",
        "Agents read existing code and follow conventions automatically",
    ),
    (r"\buse descriptive variable names\b", "Models already use descriptive names by default"),
    (r"\badd appropriate error handling\b", "Too vague — specify which errors to handle and how"),
    (r"\bwrite comprehensive tests\b", "Too vague — specify what coverage is expected"),
    (r"\bdocument your changes\b", "Too vague — specify what documentation is required"),
    (r"\bbe helpful\b", "Models are helpful by default — this has no effect"),
    (r"\bbe thorough\b", "Too vague — specify what thoroughness looks like"),
    (r"\bbe accurate\b", "Models aim for accuracy by default — this has no effect"),
    (r"\bfollow best practices\b", "Too vague — name the specific practices"),
    (r"\bwrite good tests\b", "Too vague — specify test expectations"),
    (r"\bkeep it simple\b", "Too vague — specify complexity constraints"),
    (r"\buse common sense\b", "Models cannot apply 'common sense' — be explicit"),
]

_NON_ACTIONABLE = [
    (r"\bbe aware\b", "Replace 'be aware' with an actionable instruction"),
    (r"\bkeep in mind\b", "Replace 'keep in mind' with a concrete action"),
    (r"\bnote that\b", "Restructure — state the constraint directly"),
    (r"\bremember to\b", "Replace 'remember to X' with just 'X'"),
]

_CRITICAL_KEYWORDS = re.compile(
    r"\b(IMPORTANT|MUST|NEVER|ALWAYS|CRITICAL|WARNING|REQUIRED)\b",
)

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)", re.MULTILINE)


_INSTRUCTION_FILE_CATEGORIES = {
    "AGENTS.md": "agents-md",
    "CLAUDE.md": "claude-md",
    "GEMINI.md": "gemini-md",
}


@dataclass
class ContentFile:
    path: Path
    category: str


def gather_all_content_files(context: RepositoryContext) -> List[ContentFile]:
    """Gather all contextual content files across all formats.

    Returns tagged ContentFile objects with category matching context_budget limit keys.
    Deduplicates by resolved path.
    """
    files: List[ContentFile] = []
    seen: Set[Path] = set()

    def _add(p: Path, category: str) -> None:
        resolved = p.resolve()
        if resolved not in seen and p.exists():
            seen.add(resolved)
            files.append(ContentFile(path=p, category=category))

    for f in context.instruction_files:
        cat = _INSTRUCTION_FILE_CATEGORIES.get(f.name, "instruction")
        _add(f, cat)

    _add(context.root_path / ".github" / "copilot-instructions.md", "instruction")
    _add(context.root_path / ".cursorrules", "instruction")

    cursor_rules_dir = context.root_path / ".cursor" / "rules"
    if cursor_rules_dir.is_dir():
        for mdc in sorted(cursor_rules_dir.glob("*.mdc")):
            _add(mdc, "instruction")

    kiro_steering = context.root_path / ".kiro" / "steering"
    if kiro_steering.is_dir():
        for md in sorted(kiro_steering.glob("*.md")):
            _add(md, "instruction")

    _add(context.root_path / ".windsurfrules", "instruction")

    clinerules = context.root_path / ".clinerules"
    if clinerules.is_file():
        _add(clinerules, "instruction")
    elif clinerules.is_dir():
        for md in sorted(clinerules.glob("*.md")):
            _add(md, "instruction")

    for skill_path in context.skills:
        _add(skill_path / "SKILL.md", "skill")
        refs_dir = skill_path / "references"
        if refs_dir.is_dir():
            for ref_file in sorted(refs_dir.glob("*.md")):
                _add(ref_file, "skill-ref")

    for plugin_path in context.plugins:
        commands_dir = plugin_path / "commands"
        if commands_dir.is_dir():
            for cmd_file in sorted(commands_dir.glob("*.md")):
                _add(cmd_file, "command")

        agents_dir = plugin_path / "agents"
        if agents_dir.is_dir():
            for agent_file in sorted(agents_dir.glob("*.md")):
                _add(agent_file, "agent")

        rules_dir = plugin_path / "rules"
        if rules_dir.is_dir():
            for rule_file in sorted(rules_dir.rglob("*.md")):
                _add(rule_file, "rule")

    for glob_pattern in getattr(context, "content_paths", []):
        for extra in sorted(context.root_path.glob(glob_pattern)):
            if extra.is_file():
                _add(extra, "extra")

    return files


def gather_all_instruction_files(context: RepositoryContext) -> List[Path]:
    """Gather all contextual content files across all formats.

    Thin wrapper around gather_all_content_files for backward compatibility.
    """
    return [cf.path for cf in gather_all_content_files(context)]


def _get_body(path: Path, *, strip_code_blocks: bool = True) -> Optional[str]:
    """Read file and strip YAML frontmatter if present."""
    content = read_text(path)
    if content is None:
        return None
    if path.suffix == ".mdc":
        _, body = parse_frontmatter(content)
    else:
        body = content
    if strip_code_blocks:
        body = _strip_fenced_code_blocks(body)
    return body


class WeakLanguageDetector:
    def analyze(self, path: Path) -> List[WeakLanguageMatch]:
        content = _get_body(path)
        if not content:
            return []
        results: List[WeakLanguageMatch] = []
        for line_num, line in enumerate(content.splitlines(), 1):
            for pattern, fix in _HEDGING:
                for m in re.finditer(pattern, line, re.IGNORECASE):
                    results.append(WeakLanguageMatch(line_num, m.group(), "hedging", fix))
            for pattern, fix in _VAGUENESS:
                for m in re.finditer(pattern, line, re.IGNORECASE):
                    results.append(WeakLanguageMatch(line_num, m.group(), "vagueness", fix))
            for pattern, fix in _NON_ACTIONABLE:
                for m in re.finditer(pattern, line, re.IGNORECASE):
                    results.append(WeakLanguageMatch(line_num, m.group(), "non-actionable", fix))
        return results


class DeadReferenceScanner:
    _BACKTICK_PATH = re.compile(r"`((?:\w[\w.-]*/)+[\w.-]+(?:\.\w+)?)`")
    _SEE_PATH = re.compile(
        r"(?:see|refer to|check)\s+((?:\w[\w.-]*/)+[\w.-]+(?:\.\w+)?)", re.IGNORECASE
    )
    _MD_LINK = re.compile(r"\[([^\]]*)\]\((\./[^)]+)\)")
    _NPM_SCRIPT = re.compile(r"`npm run\s+([\w:.-]+)`")
    _MAKE_TARGET = re.compile(r"`make\s+([\w.-]+)`")

    def analyze(self, path: Path, root: Path) -> List[DeadReference]:
        content = _get_body(path)
        if not content:
            return []
        results: List[DeadReference] = []
        for line_num, line in enumerate(content.splitlines(), 1):
            for m in self._BACKTICK_PATH.finditer(line):
                ref = m.group(1)
                expected = root / ref
                if not expected.exists():
                    results.append(DeadReference(line_num, ref, str(expected), False))

            for m in self._SEE_PATH.finditer(line):
                ref = m.group(1)
                expected = root / ref
                if not expected.exists():
                    results.append(DeadReference(line_num, ref, str(expected), False))

            for m in self._MD_LINK.finditer(line):
                ref = m.group(2)
                expected = (path.parent / ref).resolve()
                if not expected.exists():
                    results.append(DeadReference(line_num, ref, str(expected), False))

            for m in self._NPM_SCRIPT.finditer(line):
                script_name = m.group(1)
                pkg_json = root / "package.json"
                if pkg_json.exists():
                    pkg_content = read_text(pkg_json)
                    if pkg_content and f'"{script_name}"' not in pkg_content:
                        results.append(
                            DeadReference(
                                line_num,
                                f"npm run {script_name}",
                                str(pkg_json),
                                False,
                            )
                        )

            for m in self._MAKE_TARGET.finditer(line):
                target = m.group(1)
                makefile = root / "Makefile"
                if makefile.exists():
                    mk_content = read_text(makefile)
                    if mk_content:
                        target_re = re.compile(rf"^{re.escape(target)}\s*:", re.MULTILINE)
                        if not target_re.search(mk_content):
                            results.append(
                                DeadReference(
                                    line_num,
                                    f"make {target}",
                                    str(makefile),
                                    False,
                                )
                            )
        return results


class TautologicalDetector:
    def analyze(self, path: Path) -> List[TautologicalMatch]:
        content = _get_body(path)
        if not content:
            return []
        results: List[TautologicalMatch] = []
        for line_num, line in enumerate(content.splitlines(), 1):
            for pattern, reason in _TAUTOLOGICAL_PHRASES:
                m = re.search(pattern, line, re.IGNORECASE)
                if m:
                    results.append(TautologicalMatch(line_num, m.group(), reason))
        return results


class CriticalPositionAnalyzer:
    def analyze(self, path: Path) -> List[PositionIssue]:
        content = _get_body(path)
        if not content:
            return []
        lines = content.splitlines()
        total = len(lines)
        if total < 10:
            return []
        results: List[PositionIssue] = []
        for line_num, line in enumerate(lines, 1):
            m = _CRITICAL_KEYWORDS.search(line)
            if not m:
                continue
            position = line_num / total
            if 0.2 < position < 0.8:
                score = 0.5
                results.append(
                    PositionIssue(
                        line_num,
                        m.group(),
                        score,
                        "Move to the first 20% or last 20% of the file for better attention",
                    )
                )
        return results


class RedundancyDetector:
    _INDENT_PATTERNS = [
        (re.compile(r"\buse\s+(\d+)\s+spaces?\b", re.IGNORECASE), "indent_size"),
        (re.compile(r"\buse\s+tabs\b", re.IGNORECASE), "indent_style"),
        (re.compile(r"\bindent\s+with\s+(\d+)\s+spaces?\b", re.IGNORECASE), "indent_size"),
        (re.compile(r"\bindent\s+with\s+tabs\b", re.IGNORECASE), "indent_style"),
    ]

    def analyze(self, path: Path, root: Path) -> List[RedundancyMatch]:
        content = _get_body(path)
        if not content:
            return []
        results: List[RedundancyMatch] = []

        editorconfig = root / ".editorconfig"
        has_editorconfig = editorconfig.exists()

        eslintrc_names = [
            ".eslintrc.json",
            ".eslintrc.js",
            ".eslintrc.yml",
            ".eslintrc.yaml",
            ".eslintrc",
        ]
        has_eslint = (
            any((root / n).exists() for n in eslintrc_names)
            or (root / "eslint.config.js").exists()
            or (root / "eslint.config.mjs").exists()
        )
        prettierrc_names = [
            ".prettierrc",
            ".prettierrc.json",
            ".prettierrc.js",
            ".prettierrc.yml",
            ".prettierrc.yaml",
        ]
        has_prettier = any((root / n).exists() for n in prettierrc_names)
        has_tsconfig = (root / "tsconfig.json").exists()

        for line_num, line in enumerate(content.splitlines(), 1):
            if has_editorconfig:
                for pattern, config_key in self._INDENT_PATTERNS:
                    if pattern.search(line):
                        results.append(
                            RedundancyMatch(
                                line_num,
                                line.strip(),
                                ".editorconfig",
                                config_key,
                            )
                        )

            if has_eslint or has_prettier:
                if re.search(
                    r"\b(semicolons?|trailing commas?|single quotes?|double quotes?)\b",
                    line,
                    re.IGNORECASE,
                ):
                    config_file = (
                        ".eslintrc / .prettierrc"
                        if has_eslint and has_prettier
                        else (".eslintrc" if has_eslint else ".prettierrc")
                    )
                    results.append(
                        RedundancyMatch(
                            line_num,
                            line.strip(),
                            config_file,
                            "style rule",
                        )
                    )

            if has_tsconfig:
                if re.search(
                    r"\b(strict\s+type|enable\s+strict\s+mode|use\s+strict\s+typescript)\b",
                    line,
                    re.IGNORECASE,
                ):
                    results.append(
                        RedundancyMatch(
                            line_num,
                            line.strip(),
                            "tsconfig.json",
                            "strict mode",
                        )
                    )

        return results


class InstructionBudgetAnalyzer:
    _IMPERATIVE_RE = re.compile(
        r"^\s*[-*]?\s*(?:always|never|do not|don't|ensure|make sure|use|run|create|add|remove|check|set|write|read|call|return|throw|avoid|prefer|include|exclude|follow|implement|test|validate|verify|handle|log|format|configure|install|update|delete|move|copy|import|export|define|declare|initialize|override|extend|wrap|deploy|build|commit|push|pull|merge|rebase|review)\b",
        re.IGNORECASE,
    )
    BUDGET = 150

    def analyze(self, paths: List[Path]) -> InstructionBudget:
        total = 0
        counted: List[Path] = []
        for path in paths:
            content = _get_body(path)
            if not content:
                continue
            counted.append(path)
            for line in content.splitlines():
                if self._IMPERATIVE_RE.match(line):
                    total += 1
        remaining = self.BUDGET - total
        return InstructionBudget(
            total_count=total,
            files_counted=counted,
            budget_remaining=max(0, remaining),
            over_budget=total > self.BUDGET,
        )

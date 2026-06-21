"""
Shared content analyzers for instruction file intelligence rules.

These analyzers are called by content-* rules to detect quality issues
in instruction files across all formats (CLAUDE.md, AGENTS.md, GEMINI.md,
.cursorrules, copilot-instructions.md, .cursor/rules/*.mdc, .coderabbit.yaml).

The lint-tree block hierarchy (``ContentBlock``, ``FrontmatteredBlock``,
``JsonConfigBlock`` and all of their subclasses) now lives in the core
:mod:`skillsaw.blocks` module.  It is re-exported below so existing imports
(``from skillsaw.rules.builtin.content_analysis import SkillBlock`` etc.)
keep working unchanged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Re-exported for backward compatibility — the canonical home is
# ``skillsaw.blocks``.  Rules and tests import these block types from here.
from skillsaw.blocks import (  # noqa: F401
    AgentBlock,
    AgentsMdBlock,
    BodyContent,
    ChatmodeBlock,
    ClaudeMdBlock,
    CodeRabbitContentBlock,
    CommandBlock,
    ContentBlock,
    ContentFile,
    ContextFileBlock,
    CursorRuleBlock,
    ExtraBlock,
    FileContentBlock,
    FrontmatterField,
    FrontmatteredBlock,
    GeminiMdBlock,
    HookEventConfig,
    HookHandler,
    HooksBlock,
    InstructionBlock,
    JsonConfigBlock,
    McpBlock,
    McpServerConfig,
    ParsedFrontmatterBlock,
    PluginRuleBlock,
    PromptBlock,
    PromptfooPromptBlock,
    ReadmeBlock,
    SettingsBlock,
    SkillBlock,
    SkillRefBlock,
    _CODERABBIT_FILENAME,
    _extract_instructions,
    _find_nth_key_line,
    _find_nth_list_item_key_line,
    _find_yaml_key_line,
    _find_yaml_key_line_after,
    _get_body,
    _get_body_from_cf,
    _parse_file_frontmatter,
    _parse_json_file,
    gather_all_content_blocks,
    gather_all_content_files,
    gather_all_instruction_files,
)


@dataclass
class WeakLanguageMatch:
    line: int
    phrase: str
    category: str
    suggested_fix: str


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

_INSTRUCTION_FILE_CATEGORIES = {
    "AGENTS.md": "agents-md",
    "CLAUDE.md": "claude-md",
    "GEMINI.md": "gemini-md",
}


# ---------------------------------------------------------------------------
# Detectors — all line numbers are body-relative (1-based)
# ---------------------------------------------------------------------------


_WEAK_LANGUAGE_PATTERNS = [
    (re.compile(pattern, re.IGNORECASE), category, fix)
    for patterns, category in (
        (_HEDGING, "hedging"),
        (_VAGUENESS, "vagueness"),
        (_NON_ACTIONABLE, "non-actionable"),
    )
    for pattern, fix in patterns
]

_TAUTOLOGICAL_COMPILED = [
    (re.compile(pattern, re.IGNORECASE), reason) for pattern, reason in _TAUTOLOGICAL_PHRASES
]


try:  # Python 3.11+
    from re import _constants as _sre_constants
    from re import _parser as _sre_parser
except ImportError:  # Python 3.9/3.10
    import sre_constants as _sre_constants
    import sre_parse as _sre_parser


@lru_cache(maxsize=512)
def _required_literal(pattern_src: str, flags: int) -> Optional[str]:
    """Longest literal that every match of the pattern must contain, lowercased.

    Walks the top-level concatenation of the regex parse tree collecting
    consecutive LITERAL characters; zero-width anchors (``\\b``, ``^``…) are
    transparent, anything else ends the run.  Returns ``None`` when no
    usable literal exists (short, non-ASCII, or the pattern starts with a
    branch) — callers must then fall back to a full regex scan, so this is
    always correctness-preserving.
    """
    try:
        tree = _sre_parser.parse(pattern_src, flags)
    except Exception:
        return None
    best: List[str] = []
    current: List[str] = []
    for op, arg in tree:
        if op is _sre_constants.LITERAL:
            current.append(chr(arg))
        elif op is _sre_constants.AT:
            continue  # zero-width assertion: adjacent literals stay contiguous
        else:
            if len(current) > len(best):
                best = current
            current = []
    if len(current) > len(best):
        best = current
    literal = "".join(best)
    if len(literal) < 3 or not literal.isascii():
        return None
    return literal.lower()


def patterns_matching_anywhere(content: str, patterns: List[tuple]) -> List[tuple]:
    """Whole-text prefilter for per-line pattern scans.

    Returns the subset of ``(compiled_pattern, ...)`` tuples whose pattern
    matches anywhere in *content*, preserving order.  Any pattern that
    matches some line necessarily matches the whole text, so per-line scans
    can safely skip the rest — results are identical, but the common case
    (pattern absent from the file) is dramatically cheaper.

    Two-stage filter: a C-speed lowercase substring check on each pattern's
    required literal eliminates most patterns without running the regex
    engine at all; survivors (and patterns with no extractable literal) are
    confirmed with a real whole-text search.
    """
    lowered = content.lower()
    active = []
    for t in patterns:
        pattern = t[0]
        literal = _required_literal(pattern.pattern, pattern.flags)
        if literal is not None and literal not in lowered:
            continue
        if pattern.search(content):
            active.append(t)
    return active


class WeakLanguageDetector:
    def analyze(self, cf: ContentBlock) -> List[WeakLanguageMatch]:
        content = _get_body_from_cf(cf)
        if not content:
            return []
        active = patterns_matching_anywhere(content, _WEAK_LANGUAGE_PATTERNS)
        if not active:
            return []
        results: List[WeakLanguageMatch] = []
        for line_num, line in enumerate(content.splitlines(), 1):
            for pattern, category, fix in active:
                for m in pattern.finditer(line):
                    results.append(WeakLanguageMatch(line_num, m.group(), category, fix))
        return results


class TautologicalDetector:
    def analyze(self, cf: ContentBlock) -> List[TautologicalMatch]:
        content = _get_body_from_cf(cf)
        if not content:
            return []
        active = patterns_matching_anywhere(content, _TAUTOLOGICAL_COMPILED)
        if not active:
            return []
        results: List[TautologicalMatch] = []
        for line_num, line in enumerate(content.splitlines(), 1):
            for pattern, reason in active:
                m = pattern.search(line)
                if m:
                    results.append(TautologicalMatch(line_num, m.group(), reason))
        return results


class CriticalPositionAnalyzer:
    def __init__(self, min_lines: int = 50):
        self._min_lines = min_lines

    def analyze(self, cf: ContentBlock) -> List[PositionIssue]:
        content = _get_body_from_cf(cf)
        if not content:
            return []
        lines = content.splitlines()
        total = len(lines)
        if total < self._min_lines:
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

    def __init__(self):
        # Tooling-config presence per root — stat the filesystem once per
        # detector, not once per content block.
        self._tooling_cache: Dict[Path, Tuple[bool, bool, bool, bool]] = {}

    def _detect_tooling(self, root: Path) -> Tuple[bool, bool, bool, bool]:
        cached = self._tooling_cache.get(root)
        if cached is not None:
            return cached

        has_editorconfig = (root / ".editorconfig").exists()

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

        cached = (has_editorconfig, has_eslint, has_prettier, has_tsconfig)
        self._tooling_cache[root] = cached
        return cached

    def analyze(self, cf: ContentBlock, root: Path) -> List[RedundancyMatch]:
        has_editorconfig, has_eslint, has_prettier, has_tsconfig = self._detect_tooling(root)
        if not (has_editorconfig or has_eslint or has_prettier or has_tsconfig):
            return []
        content = _get_body_from_cf(cf)
        if not content:
            return []
        results: List[RedundancyMatch] = []

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

    def analyze_file(self, cf: ContentBlock) -> InstructionBudget:
        content = _get_body_from_cf(cf)
        if not content:
            return InstructionBudget(
                total_count=0,
                files_counted=[],
                budget_remaining=self.BUDGET,
                over_budget=False,
            )
        total = 0
        for line in content.splitlines():
            if self._IMPERATIVE_RE.match(line):
                total += 1
        remaining = self.BUDGET - total
        return InstructionBudget(
            total_count=total,
            files_counted=[cf.path],
            budget_remaining=max(0, remaining),
            over_budget=total > self.BUDGET,
        )

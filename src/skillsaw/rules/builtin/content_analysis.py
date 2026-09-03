"""
Shared content analyzers for instruction file intelligence rules.

These analyzers are called by content-* rules to detect quality issues
in instruction files across all formats (CLAUDE.md, AGENTS.md, GEMINI.md, QWEN.md,
.cursorrules, copilot-instructions.md, .cursor/rules/*.mdc, .coderabbit.yaml).

The lint-tree block hierarchy (``ContentBlock``, ``FrontmatteredBlock``,
``JsonConfigBlock`` and all of their subclasses) now lives in the core
:mod:`skillsaw.blocks` module.  It is re-exported below so existing imports
(``from skillsaw.rules.builtin.content_analysis import SkillBlock`` etc.)
keep working unchanged.
"""

from __future__ import annotations

import re
import signal
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

# Re-exported for backward compatibility — the canonical home is
# ``skillsaw.blocks``.  Rules and tests import these block types from here.
from skillsaw.blocks import (  # noqa: F401
    AgentBlock,
    AgentsMdBlock,
    BodyContent,
    ChatmodeBlock,
    ClaudeMdBlock,
    ClineWorkflowBlock,
    CodeRabbitContentBlock,
    CommandBlock,
    ContentBlock,
    ContentFile,
    ContextFileBlock,
    CopilotAgentBlock,
    CopilotPromptBlock,
    CursorCommandBlock,
    CursorHooksBlock,
    CursorMcpBlock,
    CursorPromptHookBlock,
    CursorRuleBlock,
    DevinGlobalRuleBlock,
    DevinRuleBlock,
    DevinSkillBlock,
    AntigravityMdBlock,
    ExtraBlock,
    FileContentBlock,
    FrontmatterField,
    FrontmatteredBlock,
    GeminiMdBlock,
    GrokAgentBlock,
    GrokCommandBlock,
    GrokHooksBlock,
    GrokRuleBlock,
    HookEventConfig,
    HookHandler,
    ClaudeHooksBlock,
    CodexHooksBlock,
    HooksBlock,
    MuseHooksBlock,
    InstructionBlock,
    JsonConfigBlock,
    McpConfigRole,
    McpBlock,
    McpServerConfig,
    OpenCodeAgentBlock,
    OpenCodeCommandBlock,
    ParsedFrontmatterBlock,
    PluginRuleBlock,
    PromptBlock,
    PromptfooPromptBlock,
    AgentMemoryBlock,
    AgentMemoryIndexBlock,
    QwenMdBlock,
    ReadmeBlock,
    SettingsBlock,
    SkillBlock,
    SkillRefBlock,
    VsCodeMcpBlock,
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
    "QWEN.md": "qwen-md",
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
    """Return the longest lowercased literal substring required by any match of the pattern.

    Walks the top-level regex parse tree to collect consecutive literal characters.
    Zero-width anchors (e.g. ``\\b``, ``^``) are ignored, and any other token ends
    the current run. Returns ``None`` if no usable literal is found (e.g. fewer than
    3 characters, non-ASCII, or top-level branching). Callers fall back to a full
    regex scan when ``None`` is returned.
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


def _literal_runs(sequence) -> List[str]:
    """Return runs of consecutive literal characters at the top level of *sequence*.

    Zero-width anchors are skipped since they do not consume characters in a match;
    any other non-literal token ends the current run.
    """
    runs: List[str] = []
    current: List[str] = []
    for op, arg in sequence:
        if op is _sre_constants.LITERAL:
            current.append(chr(arg))
        elif op is _sre_constants.AT:
            continue
        elif current:
            runs.append("".join(current))
            current = []
    if current:
        runs.append("".join(current))
    return runs


def _usable_literal(literal: str) -> Optional[str]:
    """Return *literal* lowercased if long enough (>= 3 chars) and ASCII."""
    if len(literal) < 3 or not literal.isascii():
        return None
    return literal.lower()


def _branch_alternatives(op, arg) -> Optional[list]:
    """Return the list of alternatives for a top-level branch or group wrapping a branch."""
    if op is _sre_constants.BRANCH:
        return arg[1]
    if op is _sre_constants.SUBPATTERN:
        inner = arg[3]  # (group, add_flags, del_flags, subpattern)
        if len(inner) == 1 and inner[0][0] is _sre_constants.BRANCH:
            return inner[0][1][1]
    return None


@lru_cache(maxsize=512)
def _required_literal_sets(pattern_src: str, flags: int) -> Tuple[Tuple[str, ...], ...]:
    """Return sets of required lowercase literals that must appear in any matching text.

    The return value is a tuple of alternative sets (an AND of ORs): for every
    inner tuple, the text must contain at least one of the string alternatives.

    For example:
    - A single literal run ``try to`` produces ``(("try to",),)``
    - An alternation ``(?:get|obtain|require)`` produces ``(("get", "obtain", "require"),)``

    If an alternative contains no usable literal or uses complex quantifiers, that
    set is omitted. Returns an empty tuple if no reliable literal requirements can
    be extracted.
    """
    try:
        tree = _sre_parser.parse(pattern_src, flags)
    except Exception:
        return ()
    sets: List[Tuple[str, ...]] = []
    for run in _literal_runs(tree):
        usable = _usable_literal(run)
        if usable is not None:
            sets.append((usable,))
    for op, arg in tree:
        alternatives = _branch_alternatives(op, arg)
        if alternatives is None:
            continue
        members: List[str] = []
        for alternative in alternatives:
            runs = _literal_runs(alternative)
            usable = _usable_literal(max(runs, key=len)) if runs else None
            if usable is None:
                break  # an alternative with no literal makes the set useless
            members.append(usable)
        else:
            if members:
                sets.append(tuple(members))
    return tuple(sets)


# Optional inline flag groups, then a leading word boundary.
_LEADING_BOUNDARY_RE = re.compile(r"^((?:\(\?[aiLmsux]+\))*)\\b")


def _gate_pattern(pattern: "re.Pattern[str]") -> "re.Pattern[str]":
    """Return a relaxed pattern with any leading ``\\b`` stripped, or *pattern* as is.

    Any match for ``\\bfoo`` is also a match for ``foo``, making the boundary-free
    version a safe gate. Stripping the leading boundary allows Python's regex engine
    to use its fast C-level literal prefix search rather than testing every character
    position.
    """
    match = _LEADING_BOUNDARY_RE.match(pattern.pattern)
    if match is None:
        return pattern
    try:
        return re.compile(match.group(1) + pattern.pattern[match.end() :], pattern.flags)
    except re.error:
        return pattern


# Cached prefilter metadata per compiled regex:
# (primary_literal, remaining_literal_sets, gate_pattern)
# The primary literal is the longest single-alternative literal, allowing a quick
# initial substring check before iterating alternative sets.
_PrefilterEntry = Tuple[Optional[str], Tuple[Tuple[str, ...], ...], "re.Pattern[str]"]
_PREFILTER_CACHE: Dict["re.Pattern[str]", _PrefilterEntry] = {}


def _prefilter_for(pattern: "re.Pattern[str]") -> _PrefilterEntry:
    entry = _PREFILTER_CACHE.get(pattern)
    if entry is None:
        if len(_PREFILTER_CACHE) >= 4096:
            _PREFILTER_CACHE.clear()  # Prevent unbounded growth from dynamically compiled patterns
        sets = list(_required_literal_sets(pattern.pattern, pattern.flags))
        first: Optional[str] = None
        singles = [alternatives[0] for alternatives in sets if len(alternatives) == 1]
        if singles:
            first = max(singles, key=len)
            sets.remove((first,))
        entry = (first, tuple(sets), _gate_pattern(pattern))
        _PREFILTER_CACHE[pattern] = entry
    return entry


def patterns_matching_anywhere(content: str, patterns: List[tuple]) -> List[tuple]:
    """Filter regex patterns down to those that match anywhere in *content*.

    Returns the subset of ``(compiled_pattern, ...)`` tuples whose pattern matches
    in *content*, preserving original order. Because a pattern must match the
    full document before it can match any individual line, filtering upfront
    allows subsequent per-line scans to skip non-matching patterns entirely.

    Uses a three-stage filter:
    1. Fast lowercase substring checks on required literals (:func:`_required_literal_sets`).
    2. A relaxed prefix gate pattern without leading word boundaries (:func:`_gate_pattern`).
    3. Full regex search on surviving candidate patterns.
    """
    lowered = content.lower()
    active = []
    for t in patterns:
        pattern = t[0]
        literal, literal_sets, gate = _prefilter_for(pattern)
        if literal is not None and literal not in lowered:
            continue
        if literal_sets:
            # Use explicit loops rather than generators to minimize per-pattern overhead
            rejected = False
            for alternatives in literal_sets:
                for candidate in alternatives:
                    if candidate in lowered:
                        break
                else:
                    rejected = True
                    break
            if rejected:
                continue
        if gate is not pattern and gate.search(content) is None:
            continue
        if pattern.search(content):
            active.append(t)
    return active


class RegexTimeout(Exception):
    """Raised when a regex operation exceeds its wall-clock budget."""


@contextmanager
def regex_timeout(seconds: float) -> Iterator[None]:
    """Bound the wall-clock time of regex work inside the ``with`` body.

    Config-supplied patterns (``.skillsaw.yaml``) run against untrusted file
    bodies with Python's backtracking ``re`` engine, so a catastrophic pattern
    can hang lint indefinitely (issue #316).  This wraps such work with a
    ``SIGALRM`` timer that raises :class:`RegexTimeout`; CPython checks for
    pending signals inside the matching loop, so an in-progress ``re.search``
    is actually interrupted.

    The timer requires ``SIGALRM`` and the main thread, so it is a **no-op**
    on platforms without ``SIGALRM`` (e.g. Windows) or when called off the main
    thread — callers must treat the timeout as best-effort hardening for the
    CI (POSIX) threat, not a hard guarantee everywhere.
    """
    if (
        seconds <= 0
        or not hasattr(signal, "SIGALRM")
        or threading.current_thread() is not threading.main_thread()
    ):
        yield
        return

    def _handle(signum, frame):
        raise RegexTimeout(f"regex exceeded {seconds:g}s budget")

    previous = signal.signal(signal.SIGALRM, _handle)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


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
    _STYLE_RULE_RE = re.compile(
        r"\b(semicolons?|trailing commas?|single quotes?|double quotes?)\b", re.IGNORECASE
    )
    _STRICT_MODE_RE = re.compile(
        r"\b(strict\s+type|enable\s+strict\s+mode|use\s+strict\s+typescript)\b", re.IGNORECASE
    )

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

        # Filter patterns against the whole document first so line-by-line checks
        # only evaluate patterns that actually appear in the content.
        active_indent = (
            patterns_matching_anywhere(content, self._INDENT_PATTERNS) if has_editorconfig else []
        )
        style_active = (has_eslint or has_prettier) and bool(
            patterns_matching_anywhere(content, [(self._STYLE_RULE_RE,)])
        )
        strict_active = has_tsconfig and bool(
            patterns_matching_anywhere(content, [(self._STRICT_MODE_RE,)])
        )
        if not active_indent and not style_active and not strict_active:
            return []

        results: List[RedundancyMatch] = []
        for line_num, line in enumerate(content.splitlines(), 1):
            for pattern, config_key in active_indent:
                if pattern.search(line):
                    results.append(
                        RedundancyMatch(
                            line_num,
                            line.strip(),
                            ".editorconfig",
                            config_key,
                        )
                    )

            if style_active and self._STYLE_RULE_RE.search(line):
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

            if strict_active and self._STRICT_MODE_RE.search(line):
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
    # `[^\S\n]*` twice with an optional bullet between them is one
    # whitespace consumer, not two: the old `^\s*[-*]?\s*` shared a
    # whitespace run between two `\s*` and backtracked O(n^2) on a long
    # run — a 20 KB HTML comment blanked to spaces cost 54 s per line.
    _IMPERATIVE_RE = re.compile(
        r"^[^\S\n]*(?:[-*][^\S\n]*)?(?:always|never|do not|don't|ensure|make sure|use|run|create|add|remove|check|set|write|read|call|return|throw|avoid|prefer|include|exclude|follow|implement|test|validate|verify|handle|log|format|configure|install|update|delete|move|copy|import|export|define|declare|initialize|override|extend|wrap|deploy|build|commit|push|pull|merge|rebase|review)\b",
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


#: A whitespace-free run longer than this is not a path reference anyone
#: wrote; blanking it keeps the path regexes linear on adversarial lines.
LONG_TOKEN_LIMIT = 256
_LONG_TOKEN_RE = re.compile(r"\S{257,}")


def blank_long_tokens(text: str) -> str:
    """Replace whitespace-free runs longer than :data:`LONG_TOKEN_LIMIT` with
    spaces of the same length, so offsets into *text* stay valid.

    The path-like regexes (`[\\w._-]+(?:/[\\w._-]+)+\\.\\w{1,10}`) are quadratic
    on one long slash-heavy token without an extension: every start
    position scans to the end and fails. Real references are short; a
    50 KB token is a payload.
    """
    if len(text) <= LONG_TOKEN_LIMIT:
        return text
    return _LONG_TOKEN_RE.sub(lambda match: " " * (match.end() - match.start()), text)


def iter_frontmatter_strings(value: Any, _seen: Optional[Set[int]] = None) -> Iterator[str]:
    """Yield every string embedded in a frontmatter value, each container once.

    Nested lists and mappings are walked (mapping keys included): a payload
    in ``allowed-tools: [Ba<ZWSP>sh]`` never surfaces through ``str(value)``
    because ``repr`` backslash-escapes format characters.

    Containers already visited are skipped by ``id``. That terminates the
    self-referential structures YAML anchor/alias cycles build, and it
    keeps a shared DAG linear: ``str()`` of ``a2: &a2 [*a1, *a1, …]`` over
    ``a1: &a1 [*a0, …]`` renders every alias as a copy — 9^levels leaves
    from a 430-byte file — where this walk visits each list once.
    """
    if isinstance(value, str):
        yield value
        return
    if not isinstance(value, (dict, list, tuple)):
        return
    if _seen is None:
        _seen = set()
    if id(value) in _seen:
        return
    _seen.add(id(value))
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str):
                yield key
            yield from iter_frontmatter_strings(item, _seen)
    else:
        for item in value:
            yield from iter_frontmatter_strings(item, _seen)

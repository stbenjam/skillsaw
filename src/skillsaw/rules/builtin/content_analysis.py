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
import sys
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

from skillsaw.utils import BudgetedMemo

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
    McpConfigRole,
    McpBlock,
    McpServerConfig,
    OpenCodeAgentBlock,
    OpenCodeCommandBlock,
    ParsedFrontmatterBlock,
    PluginRuleBlock,
    PromptBlock,
    PromptfooPromptBlock,
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


#: Charged on top of what an entry's own parts measure, for the value and
#: cost dict slots and the hash-table slack behind them.
_LITERALS_ENTRY_OVERHEAD_BYTES = 256


def _literals_cost(literals: Tuple[str, ...]) -> int:
    """What a tuple of extracted literals retains, in bytes."""
    return sys.getsizeof(literals) + sum(sys.getsizeof(literal) for literal in literals)


#: Literals per (pattern source, flags). Distinct compiled patterns
#: sharing a source — the same config parsed on a later pass — hit here
#: rather than re-walking the parse tree, which is 194 ms for a
#: 200,000-character pattern. It keys on the source, so it is that
#: string's retainer once the config is gone; hence the byte budget
#: rather than the ``lru_cache(maxsize=512)`` this replaces, whose count
#: cap let 512 oversized sources past the budget below.
_LITERALS_BY_SOURCE = BudgetedMemo(8 * 1024 * 1024)


def _required_literals(pattern_src: str, flags: int) -> Tuple[str, ...]:
    """Memoized :func:`_extract_required_literals`; see ``_LITERALS_BY_SOURCE``."""
    key = (pattern_src, flags)
    literals = _LITERALS_BY_SOURCE.values.get(key)
    if literals is None:
        literals = _extract_required_literals(pattern_src, flags)
        _LITERALS_BY_SOURCE.put(
            key,
            literals,
            _LITERALS_ENTRY_OVERHEAD_BYTES + sys.getsizeof(pattern_src) + _literals_cost(literals),
        )
    return literals


def _extract_required_literals(pattern_src: str, flags: int) -> Tuple[str, ...]:
    """Every literal a match must contain, case-folded, longest first.

    Walks the top-level concatenation of the regex parse tree collecting
    runs of consecutive LITERAL characters; zero-width anchors (``\\b``,
    ``^``…) are transparent, and anything else ends the run and is skipped
    — what is inside a branch, an optional group or a repeat may not
    appear in a given match, so nothing there is required.

    Each returned string is therefore a necessary condition on its own,
    which is what lets a caller reject on the first one that is absent.
    Testing all of them is strictly more selective than testing only the
    longest: ``\\bnever\\s+commit\\b`` requires both "never" and
    "commit", and a document containing only the first is rejected without
    the regex engine ever running.

    Runs shorter than three characters, and non-ASCII runs, are dropped:
    the first match almost any text, and the second cannot be compared
    through an ASCII lowercase fold.  Dropping them only weakens the
    filter, so the result stays correctness-preserving — an empty tuple
    means "no cheap test available, run the real scan".
    """
    try:
        tree = _sre_parser.parse(pattern_src, flags)
    except Exception:
        return ()
    runs: List[str] = []
    current: List[str] = []
    for op, arg in tree:
        if op is _sre_constants.LITERAL:
            current.append(chr(arg))
            continue
        if op is _sre_constants.AT:
            continue  # zero-width assertion: adjacent literals stay contiguous
        if current:
            runs.append("".join(current))
            current = []
    if current:
        runs.append("".join(current))
    usable = [case_fold(run) for run in runs if len(run) >= 3 and run.isascii()]
    usable.sort(key=len, reverse=True)  # most selective test first
    return tuple(usable)


def _required_literal(pattern_src: str, flags: int) -> Optional[str]:
    """The longest literal every match of the pattern must contain.

    ``None`` when the pattern offers none — callers must then fall back to
    a full regex scan.  See :func:`_required_literals`.
    """
    literals = _required_literals(pattern_src, flags)
    return literals[0] if literals else None


# Required literals per compiled pattern object.
#
# The lookup stands in front of a loop that runs once per (pattern,
# document) pair — 6,870 times on a self-lint and 39,513 linting a
# 115-skill, 41-plugin repository. An ``lru_cache`` hit hashes the
# pattern's source string and builds a key tuple where a dict keyed by
# the compiled pattern object is one identity hash. At this volume the
# difference is small in absolute terms — an extra attribute load on this
# path measured 4.3 ns, or 0.03 ms across a whole run — so the object-keyed
# dict is here because it is the simpler thing that avoids re-hashing a
# possibly enormous pattern source, not because the saving is large.
#
# The builtin patterns are module constants and number in the low
# hundreds, a few hundred bytes each; only config-supplied ones are
# compiled per run, so the bound is a backstop for a long-lived process
# linting many differently-configured repositories.
#
# Bytes, not a count. An entry is not fixed-small: nothing caps the length
# of a config-supplied pattern, and the memo is keyed by the compiled
# pattern itself, so it keeps that pattern alive after the config that
# compiled it is gone — it is the retainer, not a passenger on someone
# else's reference. A single 200,000-character pattern measures 3.4 MB
# compiled, so a count cap of 20,000 bounded this at gigabytes.
# ``sys.getsizeof`` on a compiled pattern does scale with its code array,
# so the charge is a direct measurement rather than an estimate.
_LITERALS_BY_PATTERN = BudgetedMemo(8 * 1024 * 1024)


def _literals_entry_cost(pattern: "re.Pattern", literals: Tuple[str, ...]) -> int:
    """What one ``_LITERALS_BY_PATTERN`` entry retains, in bytes."""
    return (
        _LITERALS_ENTRY_OVERHEAD_BYTES
        + sys.getsizeof(pattern)
        + sys.getsizeof(pattern.pattern)
        + _literals_cost(literals)
    )


# ``str.lower`` is not the fold ``re.IGNORECASE`` uses, and ``str.casefold``
# is not quite it either. Two Turkish dotted-i forms need normalizing on
# top: U+0131 (dotless i), which casefolds to itself, and U+0130 (capital I
# with dot above), which casefolds to "i" plus a combining dot.
# ``re.IGNORECASE`` matches both against "i".
_DOTTED_I_FORMS = ("\u0131", "i\u0307")


def case_fold(text: str) -> str:
    """Fold *text* the way ``re.IGNORECASE`` compares.

    ``str.lower`` leaves U+017F (long s) alone, while the regex engine
    matches it against "s" — so a lowercase substring gate built on it
    can reject a document the pattern would have matched. The Turkish
    dotted-i forms need a rewrite ``casefold`` does not do either; see
    ``_DOTTED_I_FORMS``.

    Being *more* permissive than the engine here would be harmless — the
    real pattern still runs on whatever survives the gate — but being less
    permissive drops findings, so the fold is checked in that direction.
    """
    folded = text.casefold()
    for form in _DOTTED_I_FORMS:
        if form in folded:
            folded = folded.replace(form, "i")
    return folded


def _pattern_literals(pattern: re.Pattern) -> Tuple[str, ...]:
    """Literals every match of *pattern* must contain (see `_required_literals`)."""
    literals = _LITERALS_BY_PATTERN.values.get(pattern)
    if literals is None:
        literals = _required_literals(pattern.pattern, pattern.flags)
        _LITERALS_BY_PATTERN.put(pattern, literals, _literals_entry_cost(pattern, literals))
    return literals


def patterns_matching_anywhere(
    content: str, patterns: List[tuple], folded: Optional[str] = None
) -> List[tuple]:
    """Whole-text prefilter for per-line pattern scans.

    Returns the subset of ``(compiled_pattern, ...)`` tuples whose pattern
    matches anywhere in *content*, preserving order.  Any pattern that
    matches some line necessarily matches the whole text, so per-line scans
    can safely skip the rest — results are identical, but the common case
    (pattern absent from the file) is dramatically cheaper.

    Two-stage filter: C-speed substring checks against every literal the
    pattern requires eliminate most patterns without running the regex
    engine at all; survivors (and patterns that require no extractable
    literal) are confirmed with a real whole-text search. Both sides are
    folded with :func:`case_fold`, which matches how ``re.IGNORECASE``
    compares — a plain ``lower()`` would reject documents the pattern
    matches.

    *folded* lets a caller running several pattern groups over one body
    supply ``case_fold(content)`` itself rather than paying a whole-body
    fold per group. It must be that fold of *content* and nothing else:
    the gate decides what the real scan never sees.
    """
    if folded is None:
        folded = case_fold(content)
    active = []
    for t in patterns:
        pattern = t[0]
        literals = _pattern_literals(pattern)
        # An explicit loop, not ``any(... for ...)``: this runs once per
        # (pattern, document) pair — 39,513 times linting a 115-skill,
        # 41-plugin repository — and the generator's per-item frame costs
        # more than the substring tests it wraps.
        missing = False
        for literal in literals:
            if literal not in folded:
                missing = True
                break
        if missing:
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
    _STYLE_PATTERNS = [
        (
            re.compile(
                r"\b(semicolons?|trailing commas?|single quotes?|double quotes?)\b",
                re.IGNORECASE,
            ),
        )
    ]
    _STRICT_TYPE_PATTERNS = [
        (
            re.compile(
                r"\b(strict\s+type|enable\s+strict\s+mode|use\s+strict\s+typescript)\b",
                re.IGNORECASE,
            ),
        )
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

        # Whole-body prefilter before any per-line scan: a pattern that
        # matches some line matches the body, so the groups that miss here
        # cannot produce a result and are dropped for every line at once.
        # Folded once and shared: a repository carrying EditorConfig,
        # ESLint or Prettier, and TypeScript runs all three groups, and
        # each would otherwise allocate its own copy of the whole body.
        folded = case_fold(content)
        indent_patterns = (
            patterns_matching_anywhere(content, self._INDENT_PATTERNS, folded)
            if has_editorconfig
            else []
        )
        style_pattern = None
        if has_eslint or has_prettier:
            matched = patterns_matching_anywhere(content, self._STYLE_PATTERNS, folded)
            style_pattern = matched[0][0] if matched else None
        strict_type_pattern = None
        if has_tsconfig:
            matched = patterns_matching_anywhere(content, self._STRICT_TYPE_PATTERNS, folded)
            strict_type_pattern = matched[0][0] if matched else None
        if not (indent_patterns or style_pattern or strict_type_pattern):
            return []

        for line_num, line in enumerate(content.splitlines(), 1):
            if indent_patterns:
                for pattern, config_key in indent_patterns:
                    if pattern.search(line):
                        results.append(
                            RedundancyMatch(
                                line_num,
                                line.strip(),
                                ".editorconfig",
                                config_key,
                            )
                        )

            if style_pattern is not None:
                if style_pattern.search(line):
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

            if strict_type_pattern is not None:
                if strict_type_pattern.search(line):
                    results.append(
                        RedundancyMatch(
                            line_num,
                            line.strip(),
                            "tsconfig.json",
                            "strict mode",
                        )
                    )

        return results


def literal_alternation(words: Sequence[str]) -> str:
    """A regex source matching any of *words*, factored into a prefix trie.

    ``re`` tries the branches of an alternation one at a time, so a flat
    ``always|never|do not|…`` of fifty verbs costs up to fifty attempts at
    every line of every document in a repository. Factoring shared
    prefixes turns most of those into a handful of character comparisons.

    The matched language is unchanged. Where one word is a prefix of
    another the factored form prefers the longer, so a caller that reads
    ``match.group()`` must not be relying on the flat form's
    first-alternative order; callers that ask only whether a match exists
    are unaffected either way.
    """
    root: Dict[str, dict] = {}
    for word in words:
        node = root
        for char in word:
            node = node.setdefault(char, {})
        node[""] = {}

    def render(node: Dict[str, dict]) -> str:
        branches = [re.escape(char) + render(node[char]) for char in sorted(k for k in node if k)]
        if not branches:
            return ""
        body = branches[0] if len(branches) == 1 else "(?:%s)" % "|".join(branches)
        if "" not in node:
            return body
        # A terminal here means a shorter word ends at this node, so
        # everything past it is optional. The continuation has to be
        # grouped first: a bare ``downloa d?`` would make only the final
        # character optional, and would no longer match "do".
        return "(?:%s)?" % body

    return render(root)


class InstructionBudgetAnalyzer:
    #: Verbs that open an instruction. Matched at the start of a line,
    #: past an optional list bullet.
    IMPERATIVE_VERBS = (
        "always",
        "never",
        "do not",
        "don't",
        "ensure",
        "make sure",
        "use",
        "run",
        "create",
        "add",
        "remove",
        "check",
        "set",
        "write",
        "read",
        "call",
        "return",
        "throw",
        "avoid",
        "prefer",
        "include",
        "exclude",
        "follow",
        "implement",
        "test",
        "validate",
        "verify",
        "handle",
        "log",
        "format",
        "configure",
        "install",
        "update",
        "delete",
        "move",
        "copy",
        "import",
        "export",
        "define",
        "declare",
        "initialize",
        "override",
        "extend",
        "wrap",
        "deploy",
        "build",
        "commit",
        "push",
        "pull",
        "merge",
        "rebase",
        "review",
    )
    _IMPERATIVE_RE = re.compile(
        r"^\s*[-*]?\s*(?:%s)\b" % literal_alternation(IMPERATIVE_VERBS),
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

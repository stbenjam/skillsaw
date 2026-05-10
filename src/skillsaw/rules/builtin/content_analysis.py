"""
Shared content analyzers for instruction file intelligence rules.

These analyzers are called by content-* rules to detect quality issues
in instruction files across all formats (CLAUDE.md, AGENTS.md, GEMINI.md,
.cursorrules, copilot-instructions.md, .cursor/rules/*.mdc, .coderabbit.yaml).
"""

import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional, Set, Tuple

import yaml

from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.utils import read_text, parse_frontmatter

_FENCED_CODE_RE = re.compile(r"^( {0,3})(`{3,}|~{3,}).*\n(?:.*\n)*?\1\2\s*$", re.MULTILINE)


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

    When APM (.apm/) is present, content is gathered from the APM source
    directories instead of compiled output directories (.claude/, .cursor/,
    .gemini/, .opencode/, .agents/).
    """
    files: List[ContentFile] = []
    seen: Set[Path] = set()
    exclude = getattr(context, "exclude_patterns", [])
    root = context.root_path.resolve()

    # Build set of compiled output directories to skip when APM is present
    apm_compiled_roots: Set[Path] = set()
    if context.has_apm:
        from skillsaw.context import RepositoryContext as _RC

        for compiled_dir_name in _RC.APM_COMPILED_DIRS:
            compiled_path = (context.root_path / compiled_dir_name).resolve()
            if compiled_path.is_dir():
                apm_compiled_roots.add(compiled_path)

    def _is_excluded(p: Path) -> bool:
        if not exclude:
            return False
        try:
            rel = str(p.resolve().relative_to(root))
        except ValueError:
            return False
        return any(fnmatch.fnmatch(rel, pat) for pat in exclude)

    def _is_in_compiled_dir(p: Path) -> bool:
        """Check if a path is inside an APM compiled output directory."""
        if not apm_compiled_roots:
            return False
        resolved = p.resolve()
        return any(resolved == excl or resolved.is_relative_to(excl) for excl in apm_compiled_roots)

    def _add(p: Path, category: str) -> None:
        resolved = p.resolve()
        if resolved not in seen and p.exists() and not _is_excluded(p):
            seen.add(resolved)
            files.append(ContentFile(path=p, category=category))

    # --- Root-level instruction files (not compiled output) ---
    for f in context.instruction_files:
        cat = _INSTRUCTION_FILE_CATEGORIES.get(f.name, "instruction")
        _add(f, cat)

    _add(context.root_path / ".github" / "copilot-instructions.md", "instruction")
    _add(context.root_path / ".cursorrules", "instruction")

    # Skip compiled output directories when APM is present
    cursor_rules_dir = context.root_path / ".cursor" / "rules"
    if cursor_rules_dir.is_dir() and not _is_in_compiled_dir(cursor_rules_dir):
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

    # --- Skills ---
    for skill_path in context.skills:
        _add(skill_path / "SKILL.md", "skill")
        refs_dir = skill_path / "references"
        if refs_dir.is_dir():
            for ref_file in sorted(refs_dir.glob("*.md")):
                _add(ref_file, "skill-ref")

    # --- Plugin content (skip compiled dirs when APM present) ---
    for plugin_path in context.plugins:
        if _is_in_compiled_dir(plugin_path):
            continue

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

    _add(context.root_path / ".coderabbit.yaml", "coderabbit")

    # --- APM source directories ---
    if context.has_apm:
        apm_dir = context.root_path / ".apm"

        # .apm/instructions/*.instructions.md
        apm_instructions = apm_dir / "instructions"
        if apm_instructions.is_dir():
            for md in sorted(apm_instructions.glob("*.instructions.md")):
                _add(md, "instruction")

        # .apm/agents/*.agent.md
        apm_agents = apm_dir / "agents"
        if apm_agents.is_dir():
            for md in sorted(apm_agents.glob("*.agent.md")):
                _add(md, "agent")

        # .apm/prompts/*.md
        apm_prompts = apm_dir / "prompts"
        if apm_prompts.is_dir():
            for md in sorted(apm_prompts.glob("*.md")):
                _add(md, "prompt")

        # .apm/chatmodes/*.md
        apm_chatmodes = apm_dir / "chatmodes"
        if apm_chatmodes.is_dir():
            for md in sorted(apm_chatmodes.glob("*.md")):
                _add(md, "chatmode")

        # .apm/context/*.md
        apm_context = apm_dir / "context"
        if apm_context.is_dir():
            for md in sorted(apm_context.glob("*.md")):
                _add(md, "context")

    # --- Extra content paths from config ---
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
    """Read file and return the instruction body text.

    Handles special file types:
    - ``.mdc``: strips YAML frontmatter.
    - ``.coderabbit.yaml``: extracts and concatenates all ``instructions``
      field values so content analyzers see only instruction text.
    """
    content = read_text(path)
    if content is None:
        return None
    if path.name == ".coderabbit.yaml":
        body = _extract_coderabbit_instructions_body(content)
    elif path.suffix == ".mdc":
        _, body = parse_frontmatter(content)
    else:
        body = content
    if strip_code_blocks:
        body = _strip_fenced_code_blocks(body)
    return body


# ---------------------------------------------------------------------------
# CodeRabbit instruction extraction helpers
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


def _extract_coderabbit_instructions_body(raw: str) -> str:
    """Extract instruction text from raw .coderabbit.yaml content.

    Parses the YAML and concatenates all ``instructions`` field values
    separated by double newlines so content analyzers see only plain text.
    Returns an empty string on parse failure or when no instructions exist.
    """
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError:
        return ""
    instructions = _extract_instructions(data, raw)
    return "\n\n".join(text for _, text, _ in instructions)


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
    def __init__(self, min_lines: int = 50):
        self._min_lines = min_lines

    def analyze(self, path: Path) -> List[PositionIssue]:
        content = _get_body(path)
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

    def analyze_file(self, path: Path) -> InstructionBudget:
        content = _get_body(path)
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
            files_counted=[path],
            budget_remaining=max(0, remaining),
            over_budget=total > self.BUDGET,
        )

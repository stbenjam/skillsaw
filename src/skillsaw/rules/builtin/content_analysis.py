"""
Shared content analyzers for instruction file intelligence rules.

These analyzers are called by content-* rules to detect quality issues
in instruction files across all formats (CLAUDE.md, AGENTS.md, GEMINI.md,
.cursorrules, copilot-instructions.md, .cursor/rules/*.mdc, .coderabbit.yaml).
"""

from __future__ import annotations

import fnmatch
import re
from abc import abstractmethod
from dataclasses import dataclass, field
from functools import lru_cache
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, Iterator, List, Optional, Set, Tuple

if TYPE_CHECKING:
    from skillsaw.markdown_doc import MarkdownDoc

import yaml

from skillsaw.context import RepositoryContext
from skillsaw.lint_target import LintTarget
from ruamel.yaml import YAML as _RuamelYAML
from ruamel.yaml import YAMLError as _RuamelYAMLError

from skillsaw.rules.builtin.utils import (
    _FRONTMATTER_RE,
    read_text,
    parse_frontmatter,
    extract_section,
    frontmatter_key_line as _frontmatter_key_line,
    _extract_frontmatter_text,
    yaml_line_map as _yaml_line_map,
    yaml_key_line as _yaml_key_line_util,
    yaml_key_line_after as _yaml_key_line_after_util,
    yaml_key_lines as _yaml_key_lines_util,
    yaml_nth_key_line as _yaml_nth_key_line_util,
    yaml_nth_list_item_key_line as _yaml_nth_list_item_key_line_util,
    yaml_node_line as _yaml_node_line_util,
)

# Markdown structure (fences, code spans, HTML comments, links, headings) is
# derived from the markdown-it-py AST — see ``skillsaw.markdown_doc``.  The
# legacy per-line regex strip helpers were removed in the GH-284 migration.


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
# ContentBlock hierarchy
# ---------------------------------------------------------------------------


@dataclass(eq=False)
class ContentBlock(LintTarget):
    """Abstract base for leaf nodes with lintable text content.

    Content blocks hold prose destined for an agent's context window —
    content-quality rules run on every one of them. Structured config
    files (hooks, MCP, settings JSON) are :class:`JsonConfigBlock`
    instead: still in the lint tree, but never linted as prose.
    """

    category: str = ""
    line_offset: int = 0
    body: Optional[str] = None
    _line_map: Optional[Callable[[int], int]] = field(default=None, repr=False)

    def file_line(self, body_line: int) -> int:
        """Translate a 1-based body line number to a 1-based file line number."""
        if self._line_map is not None:
            return self._line_map(body_line)
        return body_line + self.line_offset

    @abstractmethod
    def read_body(self, *, strip_code_blocks: bool = True) -> Optional[str]: ...

    @abstractmethod
    def write_body(self, new_body: str) -> None: ...

    @property
    def markdown(self) -> "MarkdownDoc":
        """Lazily parsed :class:`MarkdownDoc` for this block's body.

        Re-parses automatically when the underlying body text changes (the
        read caches are invalidated per file after autofixes are applied).
        """
        from skillsaw.markdown_doc import MarkdownDoc

        raw = self.read_body(strip_code_blocks=False) or ""
        cached = self.__dict__.get("_markdown_doc")
        if cached is not None and cached.body == raw:
            return cached
        doc = MarkdownDoc(raw, line_offset=self.line_offset, line_map=self._line_map)
        self.__dict__["_markdown_doc"] = doc
        return doc

    def _stripped_body(self) -> str:
        """Body with verbatim content (fences, indented code blocks, code
        spans, HTML comments) blanked, line count preserved."""
        return self.markdown.prose_text()

    def estimate_tokens(self) -> int:
        body = self.read_body()
        return len(body) // 4 if body else 0

    def tree_label(self) -> str:
        return f"{self.path.name} ({self.category})"

    def __eq__(self, other):
        if not isinstance(other, ContentBlock):
            return NotImplemented
        return type(self) is type(other) and self.resolved_path == other.resolved_path

    def __hash__(self):
        return hash((type(self), self.resolved_path))


@dataclass(eq=False)
class FileContentBlock(ContentBlock):
    """A plain file whose entire content is lintable."""

    def read_body(self, *, strip_code_blocks: bool = True) -> Optional[str]:
        if self.body is not None:
            body = self.body
        else:
            content = read_text(self.path)
            if content is None:
                return None
            body = content
        if strip_code_blocks:
            return self._stripped_body()
        return body

    def write_body(self, new_body: str) -> None:
        self.path.write_text(new_body, encoding="utf-8")


@dataclass(eq=False)
class CodeRabbitContentBlock(ContentBlock):
    """One instruction fragment from .coderabbit.yaml."""

    yaml_path: str = ""

    def read_body(self, *, strip_code_blocks: bool = True) -> Optional[str]:
        if strip_code_blocks:
            return self._stripped_body()
        return self.body if self.body is not None else ""

    def write_body(self, new_body: str) -> None:
        # ``yaml_path`` uses index-based list accessors (e.g.
        # ``reviews.path_instructions[0].instructions``) so a path glob that
        # itself contains dots/brackets (``**/*.py``) can never corrupt the
        # traversal.  Any unexpected structure degrades to a no-op rather than
        # crashing the fix run.
        try:
            ruyaml = _RuamelYAML()
            ruyaml.preserve_quotes = True
            raw = self.path.read_text(encoding="utf-8")
            data = ruyaml.load(raw)
            if data is None:
                return

            parts = [p for p in re.split(r"\.|(?=\[)", self.yaml_path) if p]
            if not parts:
                return
            node = data
            for part in parts[:-1]:
                idx_match = re.fullmatch(r"\[(\d+)\]", part)
                if idx_match:
                    idx = int(idx_match.group(1))
                    if not isinstance(node, list) or idx >= len(node):
                        return
                    node = node[idx]
                else:
                    if not isinstance(node, dict) or part not in node:
                        return
                    node = node[part]

            last_key = parts[-1]
            if not (isinstance(node, dict) and last_key in node):
                return
            node[last_key] = new_body

            buf = StringIO()
            ruyaml.dump(data, buf)
            self.path.write_text(buf.getvalue(), encoding="utf-8")
        except (OSError, UnicodeDecodeError, _RuamelYAMLError):
            return

    def tree_label(self) -> str:
        return f"{self.yaml_path} ({self.category})"

    def __eq__(self, other):
        if not isinstance(other, CodeRabbitContentBlock):
            return NotImplemented
        return self.path.resolve() == other.path.resolve() and self.yaml_path == other.yaml_path

    def __hash__(self):
        return hash((type(self), self.path.resolve(), self.yaml_path))

    # --- CodeRabbit extraction helpers (classmethods) ---

    @classmethod
    def gather(
        cls,
        context: RepositoryContext,
        seen: Set[Path],
        is_excluded: Callable[[Path], bool],
    ) -> List["CodeRabbitContentBlock"]:
        cr_path = context.root_path / ".coderabbit.yaml"
        cr_resolved = cr_path.resolve()
        if cr_resolved in seen or not cr_path.exists() or is_excluded(cr_path):
            return []
        seen.add(cr_resolved)
        cr_raw = read_text(cr_path)
        if not cr_raw:
            return []
        try:
            cr_data = yaml.safe_load(cr_raw)
        except yaml.YAMLError:
            return []
        if not cr_data:
            return []
        cr_lines = cr_raw.splitlines()
        results: List[CodeRabbitContentBlock] = []
        for label, text, line in cls._extract_instructions(cr_data, cr_raw):
            offset = 0
            if line:
                key_text = cr_lines[line - 1] if line <= len(cr_lines) else ""
                is_block_scalar = bool(re.search(r":\s*[|>]", key_text))
                offset = line if is_block_scalar else (line - 1)
            results.append(
                CodeRabbitContentBlock(
                    path=cr_path,
                    category="coderabbit",
                    line_offset=offset,
                    body=text,
                    yaml_path=label,
                )
            )
        return results

    @staticmethod
    def _find_yaml_key_line(raw: str, key: str) -> Optional[int]:
        all_lines = _yaml_key_lines_util(raw, key)
        return all_lines[-1] if all_lines else None

    @staticmethod
    def _find_yaml_key_line_after(raw: str, key: str, after_line: int) -> Optional[int]:
        return _yaml_key_line_after_util(raw, key, after_line)

    @staticmethod
    def _find_nth_key_line(raw: str, key: str, n: int) -> Optional[int]:
        return _yaml_nth_key_line_util(raw, key, n)

    @staticmethod
    def _find_nth_list_item_key_line(
        raw: str, key: str, n: int, after_line: int = 0
    ) -> Optional[int]:
        return _yaml_nth_list_item_key_line_util(raw, key, n, after_line=after_line)

    @classmethod
    def _extract_instructions(cls, data: Any, raw: str) -> List[Tuple[str, str, Optional[int]]]:
        results: List[Tuple[str, str, Optional[int]]] = []
        if not isinstance(data, dict):
            return results

        reviews = data.get("reviews")
        if isinstance(reviews, dict):
            instr = reviews.get("instructions")
            if isinstance(instr, str) and instr.strip():
                reviews_line = cls._find_yaml_key_line(raw, "reviews")
                line = None
                if reviews_line is not None:
                    line = cls._find_yaml_key_line_after(raw, "instructions", reviews_line)
                if line is None:
                    line = cls._find_yaml_key_line(raw, "instructions")
                results.append(("reviews.instructions", instr, line))

            path_instructions = reviews.get("path_instructions")
            if isinstance(path_instructions, list):
                for idx, entry in enumerate(path_instructions):
                    if not isinstance(entry, dict):
                        continue
                    pi = entry.get("instructions")
                    if isinstance(pi, str) and pi.strip():
                        # Index-based path: resolves the exact list element by
                        # position rather than by an nth-"instructions" count
                        # over the whole document (which mis-attributed lines
                        # when other 'instructions' keys preceded it).
                        yaml_path = f"reviews.path_instructions[{idx}].instructions"
                        line = _yaml_node_line_util(raw, yaml_path)
                        results.append((yaml_path, pi, line))

            tools = reviews.get("tools")
            if isinstance(tools, dict):
                for tool_name, tool_cfg in tools.items():
                    if not isinstance(tool_cfg, dict):
                        continue
                    ti = tool_cfg.get("instructions")
                    if isinstance(ti, str) and ti.strip():
                        yaml_path = f"reviews.tools.{tool_name}.instructions"
                        line = _yaml_node_line_util(raw, yaml_path)
                        results.append((yaml_path, ti, line))

            pre_merge = reviews.get("pre_merge_checks")
            if isinstance(pre_merge, dict):
                custom_checks = pre_merge.get("custom_checks")
                if isinstance(custom_checks, list):
                    for idx, check in enumerate(custom_checks):
                        if not isinstance(check, dict):
                            continue
                        ci = check.get("instructions")
                        if isinstance(ci, str) and ci.strip():
                            yaml_path = (
                                f"reviews.pre_merge_checks.custom_checks[{idx}].instructions"
                            )
                            line = _yaml_node_line_util(raw, yaml_path)
                            results.append((yaml_path, ci, line))

        chat = data.get("chat")
        if isinstance(chat, dict):
            ci = chat.get("instructions")
            if isinstance(ci, str) and ci.strip():
                chat_line = cls._find_yaml_key_line(raw, "chat")
                line = None
                if chat_line is not None:
                    line = cls._find_yaml_key_line_after(raw, "instructions", chat_line)
                if line is None:
                    line = cls._find_yaml_key_line(raw, "instructions")
                results.append(("chat.instructions", ci, line))

        return results


@dataclass(eq=False)
class PromptfooPromptBlock(ContentBlock):
    """A prompt string extracted from a promptfoo eval config."""

    yaml_path: str = ""
    category: str = "promptfoo-prompt"

    def read_body(self, *, strip_code_blocks: bool = True) -> Optional[str]:
        if strip_code_blocks:
            return self._stripped_body()
        return self.body if self.body is not None else ""

    def write_body(self, new_body: str) -> None:
        ruyaml = _RuamelYAML()
        ruyaml.preserve_quotes = True
        raw = self.path.read_text(encoding="utf-8")
        data = ruyaml.load(raw)
        if data is None or not isinstance(data, dict):
            return
        prompts = data.get("prompts")
        if not isinstance(prompts, list):
            return
        idx_str = self.yaml_path.replace("prompts[", "").rstrip("]")
        try:
            idx = int(idx_str)
        except ValueError:
            return
        if 0 <= idx < len(prompts):
            prompts[idx] = new_body
        buf = StringIO()
        ruyaml.dump(data, buf)
        self.path.write_text(buf.getvalue(), encoding="utf-8")

    def tree_label(self) -> str:
        return f"{self.yaml_path} ({self.category})"

    def __eq__(self, other):
        if not isinstance(other, PromptfooPromptBlock):
            return NotImplemented
        return self.path.resolve() == other.path.resolve() and self.yaml_path == other.yaml_path

    def __hash__(self):
        return hash((type(self), self.path.resolve(), self.yaml_path))

    _TEMPLATE_ONLY_RE = re.compile(r"^\s*\{\{.*\}\}\s*$")

    @classmethod
    def gather_from_tree(cls, root: LintTarget) -> List["PromptfooPromptBlock"]:
        from skillsaw.lint_target import PromptfooConfigNode
        from skillsaw.rules.builtin.utils import read_yaml_commented, commented_item_line

        blocks: List[PromptfooPromptBlock] = []
        for node in root.find(PromptfooConfigNode):
            if node.is_fragment:
                continue
            data, error, _ = read_yaml_commented(node.path)
            if error or not isinstance(data, dict):
                continue
            prompts = data.get("prompts")
            if not isinstance(prompts, list):
                continue
            raw_lines = read_text(node.path)
            raw_lines = raw_lines.splitlines() if raw_lines else []
            for i, prompt in enumerate(prompts):
                if not isinstance(prompt, str) or not prompt.strip():
                    continue
                if cls._TEMPLATE_ONLY_RE.match(prompt):
                    continue
                line = commented_item_line(prompts, i) or 0
                # A plain one-line item (``- "text"``) has its content on the
                # same line, so body line 1 maps to ``line`` (offset = line-1).
                # A block scalar (``- |``) starts content on the *next* line, so
                # offset = line.  Mirrors CodeRabbitContentBlock.gather.
                offset = line
                if line and 1 <= line <= len(raw_lines):
                    item_text = raw_lines[line - 1]
                    is_block_scalar = bool(re.search(r"[|>][+-]?\d*\s*$", item_text))
                    offset = line if is_block_scalar else max(line - 1, 0)
                blocks.append(
                    cls(
                        path=node.path,
                        body=prompt,
                        line_offset=offset,
                        yaml_path=f"prompts[{i}]",
                    )
                )
        return blocks


# ---------------------------------------------------------------------------
# Typed content blocks — each hardcodes its category as a class default.
# Rules discover blocks via ``find(BlockType)``; ``category`` is kept for
# backward compat (context_budget limits key on it).
# ---------------------------------------------------------------------------


@dataclass(eq=False)
class InstructionBlock(FileContentBlock):
    """Generic instruction files: .cursorrules, .windsurfrules, copilot-instructions, etc."""

    category: str = "instruction"


@dataclass(eq=False)
class ClaudeMdBlock(InstructionBlock):
    """CLAUDE.md instruction file."""

    category: str = "claude-md"


@dataclass(eq=False)
class AgentsMdBlock(InstructionBlock):
    """AGENTS.md instruction file."""

    category: str = "agents-md"


@dataclass(eq=False)
class GeminiMdBlock(InstructionBlock):
    """GEMINI.md instruction file."""

    category: str = "gemini-md"


def _parse_file_frontmatter(
    path: Path,
) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[int], str, int]:
    """Parse YAML frontmatter from a markdown file.

    Returns (frontmatter_dict, error_string, error_line, body_after_frontmatter,
    fm_line_count).  ``fm_line_count`` is the number of file lines occupied by
    the frontmatter block (including the ``---`` delimiters).
    """
    content = read_text(path)
    if content is None:
        return None, f"Failed to read file: {path}", None, "", 0
    if not content.startswith("---"):
        return None, None, None, content, 0
    fm, body, error_line = parse_frontmatter(content)
    if fm is None:
        return (
            None,
            "Invalid frontmatter (malformed YAML or missing closing ---)",
            error_line,
            body,
            0,
        )
    fm_line_count = content[: len(content) - len(body)].count("\n")
    return fm, None, None, body, fm_line_count


@dataclass(eq=False)
class FrontmatterField(LintTarget):
    """A single key-value pair from YAML frontmatter, exposed as a tree node."""

    name: str = ""
    value: Any = None
    field_line: Optional[int] = None

    def __eq__(self, other):
        if not isinstance(other, FrontmatterField):
            return NotImplemented
        return (
            type(self) is type(other)
            and self.path.resolve() == other.path.resolve()
            and self.name == other.name
        )

    def __hash__(self):
        return hash((type(self), self.path.resolve(), self.name))

    def tree_label(self) -> str:
        return f"frontmatter:{self.name}"

    def estimate_tokens(self) -> int:
        if self.value is None:
            return 0
        return len(str(self.value)) // 4


@dataclass(eq=False)
class BodyContent(ContentBlock):
    """The lintable markdown body of a frontmattered file."""

    def read_body(self, *, strip_code_blocks: bool = True) -> Optional[str]:
        if not self.body:
            return None
        if strip_code_blocks:
            return self._stripped_body()
        return self.body

    def write_body(self, new_body: str) -> None:
        content = read_text(self.path)
        if content is None or not content.startswith("---"):
            self.path.write_text(new_body, encoding="utf-8")
        else:
            fm, file_body, _ = parse_frontmatter(content)
            if fm is None:
                raise ValueError("Cannot rewrite body: frontmatter is malformed")
            fm_section = content[: len(content) - len(file_body)]
            self.path.write_text(fm_section + new_body, encoding="utf-8")
        self.body = new_body

    def tree_label(self) -> str:
        return "body"


@dataclass(eq=False)
class FrontmatteredBlock(LintTarget):
    """Container for files with YAML frontmatter followed by a markdown body.

    Not a ``ContentBlock`` itself — the lintable content lives in the
    ``BodyContent`` child node.  Frontmatter keys are exposed as
    ``FrontmatterField`` children.
    """

    category: str = ""
    content_lintable_fields: Tuple[str, ...] = ()

    def file_line(self, line: int) -> int:
        """For FrontmatteredBlock, line numbers are already file-absolute."""
        return line

    _fm_parsed: Optional[
        Tuple[Optional[Dict[str, Any]], Optional[str], Optional[int], str, int]
    ] = field(default=None, init=False, repr=False)

    def __eq__(self, other):
        if not isinstance(other, FrontmatteredBlock):
            return NotImplemented
        return type(self) is type(other) and self.resolved_path == other.resolved_path

    def __hash__(self):
        return hash((type(self), self.resolved_path))

    def walk(self) -> Iterator["LintTarget"]:
        self._ensure_parsed()
        yield from super().walk()

    def _ensure_parsed(self) -> None:
        if self._fm_parsed is None:
            self._fm_parsed = _parse_file_frontmatter(self.path)
            self._build_children()

    def _build_children(self) -> None:
        # Children change: stale find() memos on this node and its ancestors
        # must not survive (e.g. after write_frontmatter_text resets _fm_parsed).
        self.invalidate_find_cache()
        self.children = [
            c for c in self.children if not isinstance(c, (FrontmatterField, BodyContent))
        ]
        fm = self._fm_parsed[0]
        if fm:
            for key, value in fm.items():
                self.children.append(
                    FrontmatterField(
                        path=self.path,
                        name=key,
                        value=value,
                        field_line=self.key_line(key),
                        parent=self,
                    )
                )
        body_text = self._fm_parsed[3]
        if body_text:
            self.children.append(
                BodyContent(
                    path=self.path,
                    category=self.category,
                    line_offset=self._fm_parsed[4],
                    body=body_text,
                    parent=self,
                )
            )

    def field(self, name: str) -> Optional[FrontmatterField]:
        """Return the ``FrontmatterField`` child with the given key name, or ``None``."""
        for fld in self.find(FrontmatterField):
            if fld.name == name:
                return fld
        return None

    def field_value(self, name: str, default: Any = None) -> Any:
        """Return the value of the named frontmatter field, or *default*."""
        fld = self.field(name)
        return fld.value if fld is not None else default

    @property
    def has_frontmatter(self) -> bool:
        self._ensure_parsed()
        return self._fm_parsed[0] is not None

    @property
    def frontmatter_error(self) -> Optional[str]:
        self._ensure_parsed()
        return self._fm_parsed[1]

    @property
    def frontmatter_error_line(self) -> Optional[int]:
        self._ensure_parsed()
        return self._fm_parsed[2]

    @property
    def body_text(self) -> str:
        self._ensure_parsed()
        return self._fm_parsed[3]

    def key_line(self, key: str) -> Optional[int]:
        return _frontmatter_key_line(self.path, key)

    def line_map(self) -> Dict[str, int]:
        content = read_text(self.path)
        if content is None:
            return {}
        fm_text, offset = _extract_frontmatter_text(content)
        if fm_text is None:
            return {}
        return _yaml_line_map(fm_text, line_offset=offset)

    def estimate_tokens(self) -> int:
        self._ensure_parsed()
        return super().estimate_tokens()

    def tree_label(self) -> str:
        return f"{self.path.name} ({self.category})"

    def read_frontmatter_text(self) -> str:
        """Return the raw YAML text between the --- delimiters (no delimiters)."""
        content = read_text(self.path)
        if not content or not content.startswith("---"):
            return ""
        fm_text, _ = _extract_frontmatter_text(content)
        return fm_text or ""

    def write_frontmatter_text(self, new_fm_text: str) -> None:
        """Replace just the frontmatter YAML, preserving the body.

        Raises ValueError if new_fm_text is not valid YAML.
        """
        try:
            data = yaml.safe_load(new_fm_text)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML: {e}") from e
        if not isinstance(data, dict):
            raise ValueError("Frontmatter must be a YAML mapping")

        fm = new_fm_text.rstrip("\n") + "\n"

        content = read_text(self.path)
        if not content:
            self.path.write_text(f"---\n{fm}---\n", encoding="utf-8")
            self._fm_parsed = None
            self.invalidate_find_cache()
            return

        m = _FRONTMATTER_RE.match(content)
        if m:
            body_after = content[m.end() :]
            self.path.write_text(f"---\n{fm}---\n{body_after}", encoding="utf-8")
        elif content.startswith("---"):
            lines = content.split("\n")
            close_idx = None
            for i, line in enumerate(lines[1:], 1):
                if line.strip() == "---":
                    close_idx = i
                    break
            if close_idx is not None:
                body_after = "\n".join(lines[close_idx + 1 :])
                if body_after and not body_after.startswith("\n"):
                    body_after = "\n" + body_after
                self.path.write_text(f"---\n{fm}---{body_after}", encoding="utf-8")
            else:
                body_after = "\n".join(lines[1:])
                self.path.write_text(f"---\n{fm}---\n{body_after}", encoding="utf-8")
        else:
            self.path.write_text(f"---\n{fm}---\n{content}", encoding="utf-8")
        self._fm_parsed = None
        # Children will be rebuilt on the next walk — cached find() results
        # on this node and its ancestors must not serve the old fields.
        self.invalidate_find_cache()


ParsedFrontmatterBlock = FrontmatteredBlock


@dataclass(eq=False)
class CursorRuleBlock(FrontmatteredBlock):
    """.cursor/rules/*.mdc files."""

    category: str = "instruction"


@dataclass(eq=False)
class CommandBlock(FrontmatteredBlock):
    """commands/*.md in plugins."""

    category: str = "command"

    def section(self, heading: str, level: int = 2) -> str:
        content = read_text(self.path)
        if content is None:
            return ""
        return extract_section(content, heading, level)


@dataclass(eq=False)
class AgentBlock(FrontmatteredBlock):
    """agents/*.md in plugins or APM agent files."""

    category: str = "agent"


@dataclass(eq=False)
class SkillBlock(FrontmatteredBlock):
    """SKILL.md in skills."""

    category: str = "skill"


@dataclass(eq=False)
class SkillRefBlock(FileContentBlock):
    """references/*.md in skills."""

    category: str = "skill-ref"


@dataclass(eq=False)
class PluginRuleBlock(FrontmatteredBlock):
    """rules/*.md in plugins."""

    category: str = "rule"


@dataclass(eq=False)
class PromptBlock(FileContentBlock):
    """APM prompt files."""

    category: str = "prompt"


@dataclass(eq=False)
class ChatmodeBlock(FileContentBlock):
    """APM chatmode files."""

    category: str = "chatmode"


@dataclass(eq=False)
class ContextFileBlock(FileContentBlock):
    """APM context files."""

    category: str = "context"


@dataclass(eq=False)
class ExtraBlock(FileContentBlock):
    """Extra content paths from config."""

    category: str = "extra"


@dataclass(eq=False)
class ReadmeBlock(LintTarget):
    """README.md in a plugin (not injected into context)."""

    show_tokens = False

    def tree_label(self) -> str:
        return self.path.name


# ---------------------------------------------------------------------------
# JSON-based blocks: hooks and MCP
# ---------------------------------------------------------------------------


@dataclass
class HookHandler:
    """A single hook handler entry."""

    type: str
    command: Optional[str] = None
    url: Optional[str] = None
    headers: Optional[Dict[str, Any]] = None
    server: Optional[str] = None
    tool: Optional[str] = None
    input: Optional[Dict[str, Any]] = None
    prompt: Optional[str] = None
    model: Optional[str] = None
    timeout: Optional[float] = None
    async_: Optional[bool] = None
    async_rewake: Optional[bool] = None
    once: Optional[bool] = None
    if_: Optional[str] = None
    status_message: Optional[str] = None
    shell: Optional[str] = None
    allowed_env_vars: Optional[List[str]] = None

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "HookHandler":
        return cls(
            type=d.get("type", ""),
            command=d.get("command"),
            url=d.get("url"),
            headers=d.get("headers"),
            server=d.get("server"),
            tool=d.get("tool"),
            input=d.get("input"),
            prompt=d.get("prompt"),
            model=d.get("model"),
            timeout=d.get("timeout"),
            async_=d.get("async"),
            async_rewake=d.get("asyncRewake"),
            once=d.get("once"),
            if_=d.get("if"),
            status_message=d.get("statusMessage"),
            shell=d.get("shell"),
            allowed_env_vars=d.get("allowedEnvVars"),
        )


@dataclass
class HookEventConfig:
    """A single event config entry (matcher + handlers)."""

    matcher: str = ".*"
    handlers: List[HookHandler] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "HookEventConfig":
        handlers: List[HookHandler] = []
        raw_hooks = d.get("hooks", [])
        if isinstance(raw_hooks, list):
            for h in raw_hooks:
                if isinstance(h, dict):
                    handlers.append(HookHandler.from_dict(h))
        return cls(
            matcher=d.get("matcher", ".*"),
            handlers=handlers,
        )


def _parse_json_file(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    from .utils import read_json

    data, error = read_json(path)
    return data, error


@dataclass(eq=False)
class JsonConfigBlock(LintTarget):
    """Structured JSON configuration in the lint tree.

    Deliberately not a :class:`ContentBlock`: these files are machine
    configuration, not prose for an agent's context window, so
    content-quality rules never see them. Dedicated rules locate them
    with ``find(HooksBlock)`` etc. and read ``raw_data``/``parse_error``.
    """

    category: str = ""
    _parsed: Optional[Tuple[Optional[Any], Optional[str]]] = field(
        default=None, init=False, repr=False
    )

    def _ensure_parsed(self) -> None:
        if self._parsed is None:
            self._parsed = _parse_json_file(self.path)

    @property
    def parse_error(self) -> Optional[str]:
        self._ensure_parsed()
        return self._parsed[1]

    @property
    def raw_data(self) -> Optional[Dict[str, Any]]:
        self._ensure_parsed()
        data = self._parsed[0]
        return data if isinstance(data, dict) else None

    def estimate_tokens(self) -> int:
        content = read_text(self.path)
        return len(content) // 4 if content else 0

    def tree_label(self) -> str:
        return f"{self.path.name} ({self.category})"


@dataclass(eq=False)
class HooksBlock(JsonConfigBlock):
    """hooks/hooks.json in a plugin."""

    category: str = "hooks"

    @property
    def events(self) -> Dict[str, List[HookEventConfig]]:
        data = self.raw_data
        if data is None:
            return {}
        hooks_obj = data.get("hooks", {})
        if not isinstance(hooks_obj, dict):
            return {}
        result: Dict[str, List[HookEventConfig]] = {}
        for event_type, configs in hooks_obj.items():
            if not isinstance(configs, list):
                continue
            entries: List[HookEventConfig] = []
            for cfg in configs:
                if isinstance(cfg, dict):
                    entries.append(HookEventConfig.from_dict(cfg))
            if entries:
                result[event_type] = entries
        return result


@dataclass
class McpServerConfig:
    """A single MCP server configuration."""

    name: str
    type: str = "stdio"
    command: Optional[str] = None
    args: Optional[List[str]] = None
    env: Optional[Dict[str, str]] = None
    cwd: Optional[str] = None
    url: Optional[str] = None
    headers: Optional[Dict[str, Any]] = None
    headers_helper: Optional[str] = None
    startup_timeout: Optional[float] = None
    always_load: Optional[bool] = None
    oauth: Optional[Dict[str, Any]] = None

    @classmethod
    def from_dict(cls, name: str, d: Dict[str, Any]) -> "McpServerConfig":
        return cls(
            name=name,
            type=d.get("type", "stdio"),
            command=d.get("command"),
            args=d.get("args"),
            env=d.get("env"),
            cwd=d.get("cwd"),
            url=d.get("url"),
            headers=d.get("headers"),
            headers_helper=d.get("headersHelper"),
            startup_timeout=d.get("startupTimeout"),
            always_load=d.get("alwaysLoad"),
            oauth=d.get("oauth"),
        )


@dataclass(eq=False)
class McpBlock(JsonConfigBlock):
    """.mcp.json at the project root or inside a plugin."""

    category: str = "mcp"

    @property
    def servers(self) -> List[McpServerConfig]:
        data = self.raw_data
        if data is None:
            return []
        servers_dict = data.get("mcpServers", data)
        if not isinstance(servers_dict, dict):
            return []
        return [
            McpServerConfig.from_dict(name, cfg)
            for name, cfg in servers_dict.items()
            if isinstance(cfg, dict)
        ]

    @property
    def server_names(self) -> Set[str]:
        return {s.name for s in self.servers}


@dataclass(eq=False)
class SettingsBlock(JsonConfigBlock):
    """settings.json or settings.local.json in .claude/."""

    category: str = "settings"

    @property
    def hooks_events(self) -> Dict[str, List[HookEventConfig]]:
        """Extract hooks, supporting both nested and flat formats.

        Nested (hooks.json style): { matcher, hooks: [{type, command}] }
        Flat (settings.json style): { type, command, matcher? }
        """
        data = self.raw_data
        if data is None:
            return {}
        hooks_obj = data.get("hooks", {})
        if not isinstance(hooks_obj, dict):
            return {}
        result: Dict[str, List[HookEventConfig]] = {}
        for event_type, configs in hooks_obj.items():
            if not isinstance(configs, list):
                continue
            entries: List[HookEventConfig] = []
            for cfg in configs:
                if not isinstance(cfg, dict):
                    continue
                if "hooks" in cfg:
                    entries.append(HookEventConfig.from_dict(cfg))
                elif "type" in cfg:
                    handler = HookHandler.from_dict(cfg)
                    matcher = cfg.get("matcher", ".*")
                    entries.append(HookEventConfig(matcher=matcher, handlers=[handler]))
            if entries:
                result[event_type] = entries
        return result


# Backward compat aliases
ContentFile = FileContentBlock


# ---------------------------------------------------------------------------
# Gather helpers (delegated to by the lint tree builder)
# ---------------------------------------------------------------------------


def gather_all_content_blocks(context: RepositoryContext) -> List[ContentBlock]:
    """Gather all content blocks via the lint tree."""
    return context.lint_tree.content_blocks()


gather_all_content_files = gather_all_content_blocks


def gather_all_instruction_files(context: RepositoryContext) -> List[Path]:
    """Thin wrapper for backward compatibility."""
    return [block.path for block in gather_all_content_blocks(context)]


def _get_body(path: Path, *, strip_code_blocks: bool = True) -> Optional[str]:
    """Prefer ``ContentBlock.read_body()`` for new code."""
    return FileContentBlock(path=path, category="file").read_body(
        strip_code_blocks=strip_code_blocks
    )


def _get_body_from_cf(cf: ContentBlock, *, strip_code_blocks: bool = True) -> Optional[str]:
    """Backward-compat wrapper around ``ContentBlock.read_body()``."""
    return cf.read_body(strip_code_blocks=strip_code_blocks)


# ---------------------------------------------------------------------------
# CodeRabbit instruction extraction helpers (kept for backward compat)
# ---------------------------------------------------------------------------

_CODERABBIT_FILENAME = ".coderabbit.yaml"


def _find_yaml_key_line(raw: str, key: str) -> Optional[int]:
    return CodeRabbitContentBlock._find_yaml_key_line(raw, key)


def _find_yaml_key_line_after(raw: str, key: str, after_line: int) -> Optional[int]:
    return CodeRabbitContentBlock._find_yaml_key_line_after(raw, key, after_line)


def _find_nth_key_line(raw: str, key: str, n: int) -> Optional[int]:
    return CodeRabbitContentBlock._find_nth_key_line(raw, key, n)


def _find_nth_list_item_key_line(raw: str, key: str, n: int, after_line: int = 0) -> Optional[int]:
    return CodeRabbitContentBlock._find_nth_list_item_key_line(raw, key, n, after_line)


def _extract_instructions(data: Any, raw: str) -> List[Tuple[str, str, Optional[int]]]:
    return CodeRabbitContentBlock._extract_instructions(data, raw)


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

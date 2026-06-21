"""CodeRabbit (.coderabbit.yaml) instruction fragments.

:class:`CodeRabbitContentBlock` represents one instruction string pulled out of
a ``.coderabbit.yaml`` file, plus the YAML line-finding helpers used to map each
fragment back to its source line.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, List, Optional, Set, Tuple

import yaml
from ruamel.yaml import YAML as _RuamelYAML
from ruamel.yaml import YAMLError as _RuamelYAMLError

from skillsaw.utils import (
    read_text,
    yaml_key_line_after as _yaml_key_line_after_util,
    yaml_key_lines as _yaml_key_lines_util,
    yaml_nth_key_line as _yaml_nth_key_line_util,
    yaml_nth_list_item_key_line as _yaml_nth_list_item_key_line_util,
    yaml_node_line as _yaml_node_line_util,
)

from .base import ContentBlock

if TYPE_CHECKING:
    from skillsaw.context import RepositoryContext


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
                is_block_scalar = bool(
                    re.search(r":\s*[|>](?:[+-]?[1-9]|[1-9]?[+-])?\s*(?:#.*)?$", key_text)
                )
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

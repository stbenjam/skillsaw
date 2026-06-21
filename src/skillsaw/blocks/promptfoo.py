"""Promptfoo prompt content blocks.

:class:`PromptfooPromptBlock` is a prompt string extracted from a promptfoo
eval config's ``prompts`` list, linted as ordinary instruction prose.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from io import StringIO
from typing import List, Optional

from ruamel.yaml import YAML as _RuamelYAML

from skillsaw.lint_target import LintTarget
from skillsaw.utils import read_text, read_yaml_commented, commented_item_line

from .base import ContentBlock


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
                    # Block-scalar header: ``|``/``>`` plus an optional
                    # indentation indicator and chomping indicator in either
                    # order (``|``, ``|-``, ``|2``, ``|2-``, ``>2+`` ...), and an
                    # optional trailing YAML comment (``- | # system prompt``).
                    is_block_scalar = bool(
                        re.search(r"[|>](?:\d+[+-]?|[+-]?\d*)\s*(?:#.*)?$", item_text)
                    )
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

"""
Base class for all nodes in the repository lint tree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, List, Type, TypeVar

T = TypeVar("T", bound="LintTarget")


@dataclass
class LintTarget:
    """A node in the repository lint tree."""

    path: Path
    children: List["LintTarget"] = field(default_factory=list)

    def walk(self) -> Iterator["LintTarget"]:
        yield self
        for child in self.children:
            yield from child.walk()

    def find(self, target_type: Type[T]) -> List[T]:
        return [n for n in self.walk() if isinstance(n, target_type)]

    def content_blocks(self) -> list:
        from .rules.builtin.content_analysis import ContentBlock

        return self.find(ContentBlock)

    def tree_label(self) -> str:
        return self.path.name

    def print_tree(
        self, *, _prefix: str = "", _last: bool = True, root_path: Path | None = None
    ) -> str:
        lines: list[str] = []
        if root_path and self.path == root_path:
            label = f"{self.path.name}/"
        else:
            label = self.tree_label()

        if _prefix or not root_path:
            connector = "└── " if _last else "├── "
            lines.append(f"{_prefix}{connector}{label}")
        else:
            lines.append(label)

        child_prefix = _prefix + ("    " if _last else "│   ")
        for i, child in enumerate(self.children):
            is_last = i == len(self.children) - 1
            lines.append(child.print_tree(_prefix=child_prefix, _last=is_last, root_path=root_path))
        return "\n".join(lines)


@dataclass
class MarketplaceNode(LintTarget):
    """A marketplace plugins directory."""

    def tree_label(self) -> str:
        return f"{self.path.name}/ [marketplace]"


@dataclass
class PluginNode(LintTarget):
    """A plugin directory."""

    def tree_label(self) -> str:
        return f"{self.path.name}/ [plugin]"


@dataclass
class SkillNode(LintTarget):
    """A skill directory."""

    def tree_label(self) -> str:
        return f"{self.path.name}/ [skill]"

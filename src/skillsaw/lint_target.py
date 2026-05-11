"""
Base class for all nodes in the repository lint tree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, List, Optional, Type, TypeVar

T = TypeVar("T", bound="LintTarget")


@dataclass
class LintTarget:
    """A node in the repository lint tree."""

    path: Path
    children: List["LintTarget"] = field(default_factory=list)
    parent: Optional["LintTarget"] = field(default=None, repr=False)

    def walk(self) -> Iterator["LintTarget"]:
        yield self
        for child in self.children:
            yield from child.walk()

    def find(self, target_type: Type[T]) -> List[T]:
        return [n for n in self.walk() if isinstance(n, target_type)]

    def find_parent(self, target: "LintTarget", parent_type: Type[T]) -> Optional[T]:
        """Find the nearest ancestor of ``target`` that is ``parent_type``."""
        node = target.parent
        while node is not None:
            if isinstance(node, parent_type):
                return node
            node = node.parent
        return None

    def set_parents(self) -> None:
        """Set parent back-pointers for the entire subtree."""
        for child in self.children:
            child.parent = self
            child.set_parents()

    def content_blocks(self) -> list:
        from .rules.builtin.content_analysis import ContentBlock

        return self.find(ContentBlock)

    def tree_label(self) -> str:
        return self.path.name

    def estimate_tokens(self) -> int:
        return sum(c.estimate_tokens() for c in self.children)

    def _format_tokens(self, tokens: int) -> str:
        return f"{tokens:,}"

    def print_tree(
        self, *, _prefix: str = "", _last: bool = True, root_path: Path | None = None
    ) -> str:
        lines: list[str] = []
        tokens = self.estimate_tokens()
        token_str = f" ({self._format_tokens(tokens)} tokens)"
        if root_path and self.path == root_path:
            label = f"{self.path.name}/{token_str}"
        else:
            label = f"{self.tree_label()}{token_str}"

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

    def print_dot(self, *, root_path: Path | None = None) -> str:
        _COLORS = {
            "LintTarget": "#e8e8e8",
            "MarketplaceConfigNode": "#fff3cd",
            "MarketplaceNode": "#f8d7da",
            "PluginNode": "#d4edda",
            "SkillNode": "#cce5ff",
            "ApmConfigNode": "#fff3cd",
            "ApmNode": "#e2d9f3",
            "CodeRabbitNode": "#fde2e4",
            "ContentBlock": "#d1ecf1",
        }

        lines: list[str] = []
        lines.append("digraph lint_tree {")
        lines.append("    rankdir=TB;")
        lines.append('    node [shape=box, fontname="Helvetica", fontsize=10];')

        counter = [0]
        node_ids: dict[int, str] = {}

        def _node_id(node: "LintTarget") -> str:
            obj_id = id(node)
            if obj_id not in node_ids:
                node_ids[obj_id] = f"n{counter[0]}"
                counter[0] += 1
            return node_ids[obj_id]

        def _color(node: "LintTarget") -> str:
            from .rules.builtin.content_analysis import ContentBlock

            if isinstance(node, ContentBlock):
                return _COLORS["ContentBlock"]
            return _COLORS.get(type(node).__name__, _COLORS["LintTarget"])

        def _dot_label(node: "LintTarget") -> str:
            if root_path and node.path == root_path:
                name = f"{node.path.name}/"
            else:
                name = node.tree_label()
            tokens = node.estimate_tokens()
            return f"{name}\\n({node._format_tokens(tokens)} tokens)"

        def _emit(node: "LintTarget", parent_id: str | None) -> None:
            nid = _node_id(node)
            label = _dot_label(node).replace('"', '\\"')
            color = _color(node)
            lines.append(f'    {nid} [label="{label}" style=filled fillcolor="{color}"];')
            if parent_id:
                lines.append(f"    {parent_id} -> {nid};")
            for child in node.children:
                _emit(child, nid)

        _emit(self, None)
        lines.append("}")
        return "\n".join(lines)


@dataclass
class MarketplaceConfigNode(LintTarget):
    """The .claude-plugin/marketplace.json manifest file."""

    def tree_label(self) -> str:
        return "marketplace.json"


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


@dataclass
class ApmConfigNode(LintTarget):
    """The apm.yml manifest file."""

    def tree_label(self) -> str:
        return "apm.yml"


@dataclass
class ApmNode(LintTarget):
    """The .apm/ directory container."""

    def tree_label(self) -> str:
        return ".apm/"


@dataclass
class CodeRabbitNode(LintTarget):
    """A .coderabbit.yaml file container."""

    def tree_label(self) -> str:
        return ".coderabbit.yaml"

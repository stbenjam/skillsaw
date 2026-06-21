"""
Shared helpers for promptfoo eval validation rules.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional, Set

from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.lint_target import PromptfooConfigNode

# The format-detection helpers live in the dependency-light
# ``skillsaw.formats.promptfoo`` module so core (context, lint_tree) can use
# them without importing this rule package.  They are re-exported here under
# their legacy underscore names for backward compatibility.
from skillsaw.formats.promptfoo import (  # noqa: F401
    PROMPTFOO_KEYS as _PROMPTFOO_KEYS,
    extract_file_refs as _extract_file_refs,
    is_promptfoo_config as _is_promptfoo_config,
    resolve_file_ref as _resolve_file_ref,
)
from skillsaw.rules.builtin.utils import (
    commented_item_line,
    read_yaml_commented,
)

_PROMPTFOO_REPO_TYPES = {
    RepositoryType.PROMPTFOO,
}


def _get_assertion_types(assert_list: Any) -> Set[str]:
    types: Set[str] = set()
    if not isinstance(assert_list, list):
        return types
    for item in assert_list:
        if isinstance(item, dict) and isinstance(item.get("type"), str):
            types.add(item["type"])
    return types


@dataclass
class _TestInfo:
    """A test dict with its source file and line number."""

    test: dict
    file_path: Path
    line: Optional[int] = None


def _collect_tests(node: PromptfooConfigNode, context: RepositoryContext) -> List[_TestInfo]:
    """Collect all test dicts reachable from a full config node, including fragments."""
    data, error, _ = read_yaml_commented(node.path)
    if error or not isinstance(data, dict):
        return []

    tests: List[_TestInfo] = []
    raw_tests = data.get("tests")
    if isinstance(raw_tests, list):
        for i, t in enumerate(raw_tests):
            if isinstance(t, dict):
                tests.append(
                    _TestInfo(
                        test=t,
                        file_path=node.path,
                        line=commented_item_line(raw_tests, i),
                    )
                )

    for child in node.find(PromptfooConfigNode):
        if child is node:
            continue
        if not child.is_fragment:
            continue
        frag_data, frag_err, _ = read_yaml_commented(child.path)
        if frag_err:
            continue
        if isinstance(frag_data, list):
            for i, t in enumerate(frag_data):
                if isinstance(t, dict):
                    tests.append(
                        _TestInfo(
                            test=t,
                            file_path=child.path,
                            line=commented_item_line(frag_data, i),
                        )
                    )
        elif isinstance(frag_data, dict):
            tests.append(_TestInfo(test=frag_data, file_path=child.path, line=1))

    return tests

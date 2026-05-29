"""
Shared helpers for promptfoo eval validation rules.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional, Set

from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.lint_target import PromptfooConfigNode
from skillsaw.rules.builtin.utils import (
    commented_item_line,
    read_yaml_commented,
)

_PROMPTFOO_KEYS = frozenset(
    {
        "providers",
        "prompts",
        "tests",
        "scenarios",
        "defaultTest",
        "evaluateOptions",
        "redteam",
        "targets",
    }
)

_PROMPTFOO_REPO_TYPES = {
    RepositoryType.PROMPTFOO,
}


def _is_promptfoo_config(data: object) -> bool:
    """True if data is a mapping with at least one promptfoo-specific key."""
    return isinstance(data, dict) and bool(_PROMPTFOO_KEYS & set(data.keys()))


def _resolve_file_ref(ref: str, config_dir: Path) -> Optional[Path]:
    """Resolve a file:// reference relative to config_dir.

    Returns the resolved path (which may or may not exist on disk).
    Returns None for glob patterns, non-YAML extensions, and remote URLs.
    """
    if not ref.startswith("file://"):
        if ref.startswith(("http://", "https://", "huggingface://")):
            return None
        raw = ref
    else:
        raw = ref[len("file://") :]

    if not raw:
        return None
    if any(c in raw for c in ("*", "?")):
        return None

    suffix = Path(raw).suffix.lower()
    if suffix not in (".yaml", ".yml"):
        return None

    return (config_dir / raw).resolve()


def _extract_file_refs(data: dict) -> List[str]:
    """Extract string file references from a parsed promptfoo config's tests field."""
    refs: List[str] = []
    tests = data.get("tests")
    if isinstance(tests, str):
        refs.append(tests)
    elif isinstance(tests, list):
        for entry in tests:
            if isinstance(entry, str):
                refs.append(entry)
    return refs


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

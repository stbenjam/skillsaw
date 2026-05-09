"""Built-in tool definitions for the LLM engine."""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any, Dict, Optional, Protocol, Set, TYPE_CHECKING

if TYPE_CHECKING:
    from ..config import LinterConfig


class LLMTool(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def parameters(self) -> Dict[str, Any]: ...

    def execute(self, **kwargs: Any) -> str: ...


def _resolve_safe(root: Path, path: str) -> Optional[Path]:
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root.resolve()):
        return None
    return resolved


class ReadFileTool:
    name = "read_file"
    description = "Read the contents of a file"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path relative to repo root"}
        },
        "required": ["path"],
    }

    def __init__(self, root: Path):
        self._root = root

    def execute(self, *, path: str) -> str:
        resolved = _resolve_safe(self._root, path)
        if resolved is None:
            return "Error: path escapes repository root"
        if not resolved.exists():
            return f"Error: file not found: {path}"
        return resolved.read_text(encoding="utf-8")


class WriteFileTool:
    name = "write_file"
    description = "Overwrite a file with new content"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path relative to repo root"},
            "content": {"type": "string", "description": "New file content"},
        },
        "required": ["path", "content"],
    }

    def __init__(self, root: Path):
        self._root = root

    def execute(self, *, path: str, content: str) -> str:
        resolved = _resolve_safe(self._root, path)
        if resolved is None:
            return "Error: path escapes repository root"
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} bytes to {path}"


class ReplaceSectionTool:
    name = "replace_section"
    description = "Replace a section of text in a file (surgical edit)"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path relative to repo root"},
            "old_text": {"type": "string", "description": "Text to find and replace"},
            "new_text": {"type": "string", "description": "Replacement text"},
        },
        "required": ["path", "old_text", "new_text"],
    }

    def __init__(self, root: Path):
        self._root = root

    def execute(self, *, path: str, old_text: str, new_text: str) -> str:
        resolved = _resolve_safe(self._root, path)
        if resolved is None:
            return "Error: path escapes repository root"
        if not resolved.exists():
            return f"Error: file not found: {path}"
        content = resolved.read_text(encoding="utf-8")
        count = content.count(old_text)
        if count == 0:
            return "Error: old_text not found in file"
        if count > 1:
            return f"Error: old_text found {count} times — provide a more unique string"
        new_content = content.replace(old_text, new_text, 1)
        resolved.write_text(new_content, encoding="utf-8")
        return f"Replaced 1 occurrence in {path}"


class LintTool:
    name = "lint"
    description = "Run skillsaw lint on a file and return violations"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path relative to repo root"}
        },
        "required": ["path"],
    }

    def __init__(
        self, root: Path, config: "LinterConfig", rule_ids: Optional[Set[str]] = None
    ):
        self._root = root
        self._config = config
        self._rule_ids = rule_ids

    def execute(self, *, path: str) -> str:
        resolved = _resolve_safe(self._root, path)
        if resolved is None:
            return "Error: path escapes repository root"

        from ..context import RepositoryContext
        from ..rules.builtin import BUILTIN_RULES
        from ..rules.builtin.utils import invalidate_read_caches
        from ..rule import Rule

        invalidate_read_caches()
        context = RepositoryContext(self._root)
        context.content_paths = self._config.content_paths

        violations = []
        for rule_class in BUILTIN_RULES:
            rule = rule_class()
            if self._rule_ids and rule.rule_id not in self._rule_ids:
                continue
            config = self._config.get_rule_config(rule.rule_id)
            if config:
                rule = rule_class(config)
            if not self._config.is_rule_enabled(
                rule.rule_id, context, rule.repo_types, rule.formats
            ):
                continue
            try:
                rule_violations = rule.check(context)
                violations.extend(
                    v
                    for v in rule_violations
                    if v.file_path and v.file_path.resolve() == resolved
                )
            except Exception:
                pass

        if not violations:
            return "No violations found."
        return "\n".join(str(v) for v in violations)


class DiffTool:
    name = "diff"
    description = "Show unified diff of current file vs original"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path relative to repo root"}
        },
        "required": ["path"],
    }

    def __init__(self, root: Path, originals: Dict[Path, str]):
        self._root = root
        self._originals = originals

    def execute(self, *, path: str) -> str:
        resolved = _resolve_safe(self._root, path)
        if resolved is None:
            return "Error: path escapes repository root"
        if resolved not in self._originals:
            return "Error: no original snapshot for this file"
        original = self._originals[resolved].splitlines(keepends=True)
        current = resolved.read_text(encoding="utf-8").splitlines(keepends=True)
        diff = difflib.unified_diff(original, current, fromfile=f"a/{path}", tofile=f"b/{path}")
        result = "".join(diff)
        return result or "No changes."

"""Documented OpenAI skill metadata and catalog-compatible plugin metadata."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Tuple

from skillsaw.lint_target import LintTarget
from skillsaw.utils import read_yaml_commented


@dataclass(eq=False)
class OpenAIMetadataBlock(LintTarget):
    """Structured skill metadata or observed plugin-root compatibility data."""

    metadata_root: Path = Path(".")
    containment_root: Path = Path(".")
    _parsed: Optional[Tuple[Any, Optional[str], Optional[int]]] = field(
        default=None, init=False, repr=False
    )

    def _ensure_parsed(self) -> None:
        if self._parsed is None:
            self._parsed = read_yaml_commented(self.path)

    @property
    def raw_data(self) -> Any:
        self._ensure_parsed()
        return self._parsed[0]

    @property
    def parse_error(self) -> Optional[str]:
        self._ensure_parsed()
        return self._parsed[1]

    @property
    def error_line(self) -> Optional[int]:
        self._ensure_parsed()
        return self._parsed[2]

    def tree_label(self) -> str:
        return "openai.yaml [openai metadata]"

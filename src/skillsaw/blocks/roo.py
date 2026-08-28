"""Legacy Roo Code ``.roomodes`` custom-mode definitions.

A direct :class:`~skillsaw.lint_target.LintTarget`, deliberately neither a
``ContentBlock`` (the content rules would read its YAML as instruction
prose) nor a ``JsonConfigBlock`` (that hierarchy is JSON-specific and
carries no line numbers). Same shape as
:class:`~skillsaw.blocks.openai.OpenAIMetadataBlock`: parse once, lazily,
through ``read_yaml_commented`` so every violation keeps a real line.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Tuple

from skillsaw.lint_target import LintTarget
from skillsaw.utils import read_yaml_commented


@dataclass(eq=False)
class RooModesBlock(LintTarget):
    """A ``.roomodes`` file: Roo Code's custom-mode definitions."""

    _parsed: Optional[Tuple[Any, Optional[str], Optional[int]]] = field(
        default=None, init=False, repr=False
    )

    def _ensure_parsed(self) -> Tuple[Any, Optional[str], Optional[int]]:
        if self._parsed is None:
            self._parsed = read_yaml_commented(self.path)
        return self._parsed

    @property
    def raw_data(self) -> Any:
        return self._ensure_parsed()[0]

    @property
    def parse_error(self) -> Optional[str]:
        return self._ensure_parsed()[1]

    @property
    def error_line(self) -> Optional[int]:
        return self._ensure_parsed()[2]

    def tree_label(self) -> str:
        return ".roomodes [roo custom modes]"

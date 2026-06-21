"""Backward-compatibility shim for the shared YAML/JSON/text helpers.

The implementation moved to the core :mod:`skillsaw.utils` module so that
core modules (``blocks``, ``context``, ``lint_tree``) can use it without
importing this rule package (which would invert the layering and create an
import cycle).  Rule modules, custom rules, and tests that still do
``from skillsaw.rules.builtin.utils import ...`` keep working unchanged via
the re-exports below.
"""

from skillsaw.utils import *  # noqa: F401,F403
from skillsaw.utils import (  # noqa: F401  — underscore names ``*`` does not re-export
    _FRONTMATTER_RE,
    _extract_frontmatter_text,
    _fast_top_level_key_lines,
)

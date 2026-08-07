"""
Shared helpers for instruction file rules
"""

import re

INSTRUCTION_FILES = ("AGENTS.md", "CLAUDE.md", "GEMINI.md")

# Public: content-progressive-disclosure imports this cross-package, so the
# ``@path`` grammar has exactly one definition.
IMPORT_RE = re.compile(r"(?<![\w./-])@([^\s`<>'\"(){}\[\],;:]+)")

# Backward-compat alias for the pre-public name.
_IMPORT_RE = IMPORT_RE

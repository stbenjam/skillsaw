"""Format-level helpers shared across core and rule modules.

Pure, dependency-light helpers for recognizing and resolving third-party
config formats (e.g. promptfoo eval configs).  These live outside the rule
packages so core modules (``context``, ``lint_tree``) can depend on them
without reaching into a leaf rule package.
"""

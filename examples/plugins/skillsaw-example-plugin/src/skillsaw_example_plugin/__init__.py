"""Example skillsaw plugin.

The ``skillsaw.plugins`` entry point in pyproject.toml points here;
``SKILLSAW_RULES`` declares which rule classes the plugin provides.
"""

from .rules import NoTodoInstructionsRule

SKILLSAW_RULES = [NoTodoInstructionsRule]

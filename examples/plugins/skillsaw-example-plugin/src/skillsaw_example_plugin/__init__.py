"""Example skillsaw plugin.

The ``skillsaw.plugins`` entry point in pyproject.toml points here; the
``SKILLSAW_*`` declarations below are what skillsaw discovers:

- ``SKILLSAW_RULES`` — the rule classes the plugin provides
- ``SKILLSAW_REPO_TYPES`` — custom repository types with detection
- ``SKILLSAW_TREE_CONTRIBUTORS`` — callables adding nodes to the lint tree
"""

from .extensions import ACME_REPO_TYPE, AcmeConfigVersionRule, contribute_acme_config
from .rules import NoTodoInstructionsRule

SKILLSAW_RULES = [NoTodoInstructionsRule, AcmeConfigVersionRule]

SKILLSAW_REPO_TYPES = [ACME_REPO_TYPE]

SKILLSAW_TREE_CONTRIBUTORS = [contribute_acme_config]

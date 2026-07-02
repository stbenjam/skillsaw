"""Plugin fixture declaring an absolute content_paths glob.

Regression fixture: ``Path.glob()`` raises NotImplementedError on absolute
patterns, and the lint tree builds lazily inside every rule's check() — an
unvalidated absolute glob used to produce one rule-execution-error per rule.
It must instead be rejected at load time as a single plugin-load-error.
"""

from skillsaw.plugins import PluginRepoType

SKILLSAW_RULES = []

SKILLSAW_REPO_TYPES = [
    PluginRepoType(
        name="abspath",
        description="Fixture repo type with an absolute content_paths glob",
        detect=lambda root: True,
        content_paths=["/etc/*.conf"],
    ),
]

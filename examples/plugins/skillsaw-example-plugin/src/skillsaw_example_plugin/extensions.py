"""Extension points: a custom repository type and a lint tree contributor.

This demonstrates the two ways a plugin extends skillsaw beyond rules,
using a fictional "ACME" assistant whose repositories carry an ACME.md
instruction file and an .acme/ directory:

- The ``PluginRepoType`` teaches skillsaw to *recognize* ACME repositories.
  When detected, rules can scope to the type (``repo_types = {"acme"}``)
  and the type's ``content_paths`` files get every ``content-*`` rule.
- The tree contributor attaches ``.acme/config.json`` to the lint tree as
  a config block, so dedicated rules can lint it via ``lint_tree.find()``.
"""

from dataclasses import dataclass
from typing import List

from skillsaw import RepositoryContext, Rule, RuleViolation, Severity
from skillsaw.blocks import JsonConfigBlock
from skillsaw.plugins import PluginRepoType

ACME_REPO_TYPE = PluginRepoType(
    name="acme",
    description="Repository configured for the ACME assistant",
    detect=lambda root: (root / "ACME.md").exists() or (root / ".acme").is_dir(),
    # Pulled into content linting when the type is detected — matched files
    # become content blocks and get all content-* rules automatically.
    content_paths=["ACME.md", ".acme/rules/*.md"],
)


@dataclass(eq=False)
class AcmeConfigBlock(JsonConfigBlock):
    """.acme/config.json — machine config, never linted as prose."""

    category: str = "acme-config"


def contribute_acme_config(context, root):
    """Attach .acme/config.json to the lint tree when present."""
    config_path = context.root_path / ".acme" / "config.json"
    if config_path.exists():
        return [AcmeConfigBlock(path=config_path)]
    return []


class AcmeConfigVersionRule(Rule):
    """Runs only on detected ACME repositories (string repo type entry)."""

    repo_types = {"acme"}

    @property
    def rule_id(self) -> str:
        return "acme-config-version"

    @property
    def description(self) -> str:
        return "ACME config must declare a version field"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        for block in context.lint_tree.find(AcmeConfigBlock):
            if block.parse_error:
                violations.append(
                    self.violation(f"Invalid JSON: {block.parse_error}", file_path=block.path)
                )
            elif not isinstance(block.raw_data, dict) or "version" not in block.raw_data:
                violations.append(
                    self.violation("Missing required 'version' field", file_path=block.path)
                )
        return violations

"""Check literal local Goose subrecipe paths without resolving runtime sources."""

from skillsaw.blocks.goose import GooseRecipeBlock
from skillsaw.context import RepositoryType
from skillsaw.discovery.goose import existing_subrecipe, local_subrecipe
from skillsaw.rule import Rule, Severity


class GooseSubrecipeReferencesRule(Rule):
    """Check paths under the declared lint root; external sources remain runtime concerns."""

    since = "0.21.1"
    default_enabled = False
    repo_types = frozenset({RepositoryType.GOOSE})

    @property
    def rule_id(self):
        return "goose-subrecipe-references"

    @property
    def description(self):
        return "Literal local Goose subrecipe paths should exist inside the lint root"

    def default_severity(self):
        return Severity.WARNING

    def check(self, context):
        violations = []
        for block in context.lint_tree.find(GooseRecipeBlock):
            data = block.raw_data
            entries = data.get("sub_recipes") if isinstance(data, dict) else None
            if not isinstance(entries, list):
                continue
            missing = []
            for index, entry in enumerate(entries):
                value = entry.get("path") if isinstance(entry, dict) else None
                if not isinstance(value, str):
                    continue
                target = local_subrecipe(
                    value, block.path, block.workspace, context.root_path, context.resolve_path
                )
                if target is not None and not existing_subrecipe(target):
                    missing.append((f"sub_recipes[{index}].path", block.key_line(entry, "path")))
            if missing:
                fields = ", ".join(field for field, _ in missing[:5])
                violations.append(
                    self.violation(
                        f"Local subrecipe files are missing at {fields}; correct the paths or exclude generated recipes",
                        file_path=block.path,
                        line=missing[0][1],
                    )
                )
        return violations

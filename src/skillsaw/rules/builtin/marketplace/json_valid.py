"""
Rule: marketplace-json-valid
"""

import re
from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.lint_target import MarketplaceConfigNode
from skillsaw.rules.builtin.utils import read_json

_KEBAB_CASE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

# Required fields for each object source type per the plugin-marketplaces
# docs; unknown types get a warning rather than an error so a new source
# type added upstream never breaks existing marketplaces.
_SOURCE_REQUIRED_FIELDS = {
    "github": ("repo",),
    "url": ("url",),
    "git-subdir": ("url", "path"),
    "npm": ("package",),
}


class MarketplaceJsonValidRule(Rule):
    """Check that marketplace.json is valid"""

    repo_types = {RepositoryType.MARKETPLACE}

    @property
    def rule_id(self) -> str:
        return "marketplace-json-valid"

    @property
    def description(self) -> str:
        return "Marketplace.json must be valid JSON with required fields"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        # Only check if marketplace exists
        if RepositoryType.MARKETPLACE not in context.repo_types:
            return violations

        config_nodes = context.lint_tree.find(MarketplaceConfigNode)
        if not config_nodes:
            violations.append(
                self.violation(
                    "Marketplace file not found",
                    file_path=context.root_path / ".claude-plugin" / "marketplace.json",
                )
            )
            return violations

        marketplace_file = config_nodes[0].path

        # Try to parse
        marketplace, error = read_json(marketplace_file)
        if error:
            violations.append(self.violation(f"Invalid JSON: {error}", file_path=marketplace_file))
            return violations

        # Validate that marketplace is a dictionary
        if not isinstance(marketplace, dict):
            violations.append(
                self.violation(
                    "Marketplace file must contain a JSON object", file_path=marketplace_file
                )
            )
            return violations

        # Validate required fields
        if "name" not in marketplace:
            violations.append(self.violation("Missing 'name' field", file_path=marketplace_file))
        elif isinstance(marketplace["name"], str) and not _KEBAB_CASE.match(marketplace["name"]):
            violations.append(
                self.violation(
                    f"Marketplace name '{marketplace['name']}' should be kebab-case "
                    "(lowercase letters, numbers, and hyphens)",
                    file_path=marketplace_file,
                    severity=Severity.WARNING,
                )
            )

        if "owner" not in marketplace:
            violations.append(self.violation("Missing 'owner' field", file_path=marketplace_file))
        elif not isinstance(marketplace["owner"], dict):
            violations.append(
                self.violation("'owner' must be an object", file_path=marketplace_file)
            )
        elif "name" not in marketplace["owner"]:
            violations.append(
                self.violation("'owner' must have a 'name' field", file_path=marketplace_file)
            )

        if "plugins" not in marketplace:
            violations.append(self.violation("Missing 'plugins' array", file_path=marketplace_file))
        elif not isinstance(marketplace["plugins"], list):
            violations.append(
                self.violation("'plugins' must be an array", file_path=marketplace_file)
            )
        else:
            seen_names = {}
            for idx, entry in enumerate(marketplace["plugins"]):
                if not isinstance(entry, dict):
                    violations.append(
                        self.violation(
                            f"plugins[{idx}] must be an object",
                            file_path=marketplace_file,
                        )
                    )
                    continue

                if "name" not in entry:
                    violations.append(
                        self.violation(
                            f"plugins[{idx}] missing required 'name' field",
                            file_path=marketplace_file,
                        )
                    )
                elif isinstance(entry["name"], str):
                    name = entry["name"]
                    if name in seen_names:
                        violations.append(
                            self.violation(
                                f"plugins[{idx}] duplicate plugin name '{name}' "
                                f"(first defined at plugins[{seen_names[name]}])",
                                file_path=marketplace_file,
                            )
                        )
                    else:
                        seen_names[name] = idx

                if "source" not in entry:
                    violations.append(
                        self.violation(
                            f"plugins[{idx}] missing required 'source' field",
                            file_path=marketplace_file,
                        )
                    )
                else:
                    violations.extend(self._check_source(entry["source"], idx, marketplace_file))

        return violations

    def _check_source(self, source, idx: int, marketplace_file) -> List[RuleViolation]:
        """Validate a plugin entry's source (relative path or typed object)."""
        violations = []

        if isinstance(source, str):
            parts = source.replace("\\", "/").split("/")
            if ".." in parts:
                violations.append(
                    self.violation(
                        f"plugins[{idx}].source: path contains '..' — sources must "
                        "stay within the marketplace repository",
                        file_path=marketplace_file,
                    )
                )
            elif not source.startswith("./"):
                violations.append(
                    self.violation(
                        f"plugins[{idx}].source: relative path '{source}' should "
                        "start with './'",
                        file_path=marketplace_file,
                        severity=Severity.INFO,
                    )
                )
            return violations

        if not isinstance(source, dict):
            violations.append(
                self.violation(
                    f"plugins[{idx}].source must be a relative path string or an object",
                    file_path=marketplace_file,
                )
            )
            return violations

        source_type = source.get("source")
        if not isinstance(source_type, str):
            violations.append(
                self.violation(
                    f"plugins[{idx}].source object missing required 'source' type field",
                    file_path=marketplace_file,
                )
            )
            return violations

        if source_type not in _SOURCE_REQUIRED_FIELDS:
            violations.append(
                self.violation(
                    f"plugins[{idx}].source: unknown source type '{source_type}' "
                    f"(known types: {', '.join(sorted(_SOURCE_REQUIRED_FIELDS))})",
                    file_path=marketplace_file,
                    severity=Severity.WARNING,
                )
            )
            return violations

        for required in _SOURCE_REQUIRED_FIELDS[source_type]:
            if required not in source:
                violations.append(
                    self.violation(
                        f"plugins[{idx}].source of type '{source_type}' requires "
                        f"a '{required}' field",
                        file_path=marketplace_file,
                    )
                )

        return violations

"""
Rule: codex-marketplace-json-valid
"""

from pathlib import Path
from typing import Any, List
from urllib.parse import urlparse

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.lint_target import CodexMarketplaceConfigNode
from skillsaw.rules.builtin.utils import read_json

from ._helpers import CODEX_MARKETPLACE_REPO_TYPES, KEBAB_CASE, path_problem

# Required fields per documented source type. Unknown types warn rather than
# error so a source type added upstream never breaks existing marketplaces.
_SOURCE_REQUIRED_FIELDS = {
    "local": ("path",),
    "url": ("url",),
    "git-subdir": ("url", "path"),
    "npm": ("package",),
}

# "Use policy.installation values such as AVAILABLE, INSTALLED_BY_DEFAULT,
# or NOT_AVAILABLE" — the docs hedge with "such as", so an unrecognized
# value is a warning, not an error, and the set is configurable.
DEFAULT_INSTALLATION_VALUES = ["AVAILABLE", "INSTALLED_BY_DEFAULT", "NOT_AVAILABLE"]

# The public docs describe policy.authentication only in prose ("whether auth
# happens on install or first use"); these two literals are the ones the
# openai/plugins catalog and its authoring spec actually use. Open-ended for
# the same reason as installation, so unrecognized values warn.
DEFAULT_AUTHENTICATION_VALUES = ["ON_INSTALL", "ON_USE"]

# The docs mandate these on every entry ("Always include policy.installation,
# policy.authentication, and category on each plugin entry") but Codex still
# loads an entry without them, so their absence is a warning.
_RECOMMENDED_ENTRY_FIELDS = ("policy", "category")


class CodexMarketplaceJsonValidRule(Rule):
    """Check that the Codex marketplace manifest is valid"""

    repo_types = CODEX_MARKETPLACE_REPO_TYPES
    since = "0.18.0"

    config_schema = {
        "installation-values": {
            "type": "list",
            "default": DEFAULT_INSTALLATION_VALUES,
            "description": "Recognized policy.installation values",
        },
        "authentication-values": {
            "type": "list",
            "default": DEFAULT_AUTHENTICATION_VALUES,
            "description": "Recognized policy.authentication values",
        },
    }

    @property
    def rule_id(self) -> str:
        return "codex-marketplace-json-valid"

    @property
    def description(self) -> str:
        return ".agents/plugins/marketplace.json must be valid JSON with required fields"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []

        for node in context.lint_tree.find(CodexMarketplaceConfigNode):
            marketplace_file = node.path
            data, error = read_json(marketplace_file)
            if error:
                violations.append(
                    self.violation(f"Invalid JSON: {error}", file_path=marketplace_file)
                )
                continue
            if not isinstance(data, dict):
                violations.append(
                    self.violation(
                        "Marketplace file must contain a JSON object",
                        file_path=marketplace_file,
                    )
                )
                continue

            if "name" not in data:
                violations.append(
                    self.violation("Missing 'name' field", file_path=marketplace_file)
                )
            elif not isinstance(data["name"], str) or not data["name"]:
                violations.append(
                    self.violation("'name' must be a non-empty string", file_path=marketplace_file)
                )

            interface = data.get("interface")
            if interface is not None and not isinstance(interface, dict):
                violations.append(
                    self.violation("'interface' must be an object", file_path=marketplace_file)
                )

            violations.extend(self._check_plugins(data, marketplace_file))

        return violations

    def _check_plugins(self, data: dict, marketplace_file: Path) -> List[RuleViolation]:
        violations: List[RuleViolation] = []

        if "plugins" not in data:
            return [self.violation("Missing 'plugins' array", file_path=marketplace_file)]
        entries = data["plugins"]
        if not isinstance(entries, list):
            return [self.violation("'plugins' must be an array", file_path=marketplace_file)]

        seen_names: dict = {}
        for idx, entry in enumerate(entries):
            if not isinstance(entry, dict):
                violations.append(
                    self.violation(f"plugins[{idx}] must be an object", file_path=marketplace_file)
                )
                continue

            violations.extend(self._check_entry_name(entry, idx, marketplace_file, seen_names))

            if "source" not in entry:
                violations.append(
                    self.violation(
                        f"plugins[{idx}] missing required 'source' field",
                        file_path=marketplace_file,
                    )
                )
            else:
                violations.extend(self._check_source(entry["source"], idx, marketplace_file))

            for field in _RECOMMENDED_ENTRY_FIELDS:
                # ``None`` counts as absent throughout — an explicit null
                # carries no more information than a missing key, and
                # treating it as present would skip every check below it.
                if entry.get(field) is None:
                    violations.append(
                        self.violation(
                            f"plugins[{idx}] missing '{field}' — the spec asks for "
                            "policy.installation, policy.authentication and "
                            "category on every entry",
                            file_path=marketplace_file,
                            severity=Severity.WARNING,
                        )
                    )

            violations.extend(self._check_policy(entry.get("policy"), idx, marketplace_file))

        return violations

    def _check_entry_name(
        self, entry: dict, idx: int, marketplace_file: Path, seen_names: dict
    ) -> List[RuleViolation]:
        if "name" not in entry:
            return [
                self.violation(
                    f"plugins[{idx}] missing required 'name' field",
                    file_path=marketplace_file,
                )
            ]
        name = entry["name"]
        if not isinstance(name, str):
            return [
                self.violation(
                    f"plugins[{idx}] plugin name must be a string, got {name!r}",
                    file_path=marketplace_file,
                )
            ]
        # A duplicate falls through to the casing check rather than returning:
        # two entries named ``Bad_Name`` have both defects, and reporting only
        # the duplicate would hide the second until the first was fixed.
        violations: List[RuleViolation] = []
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
        if not KEBAB_CASE.match(name):
            violations.append(
                self.violation(
                    f"plugins[{idx}] plugin name '{name}' should use kebab-case",
                    file_path=marketplace_file,
                    severity=Severity.WARNING,
                )
            )
        return violations

    def _check_source(self, source: Any, idx: int, marketplace_file: Path) -> List[RuleViolation]:
        """Validate an entry's source (bare local path string or typed object)."""
        violations: List[RuleViolation] = []

        if isinstance(source, str):
            # "For local entries, source can also be a plain string path."
            violations.extend(
                self._check_local_path(source, f"plugins[{idx}].source", marketplace_file)
            )
            return violations

        if not isinstance(source, dict):
            return [
                self.violation(
                    f"plugins[{idx}].source must be a relative path string or an object",
                    file_path=marketplace_file,
                )
            ]

        source_type = source.get("source")
        # An empty discriminator is missing, not unknown: Codex cannot
        # resolve the entry either way, so it must not fall through to the
        # forward-compatibility warning and pass a default ``fail-on: error``.
        if not isinstance(source_type, str) or not source_type:
            return [
                self.violation(
                    f"plugins[{idx}].source object missing required 'source' type field",
                    file_path=marketplace_file,
                )
            ]

        if source_type not in _SOURCE_REQUIRED_FIELDS:
            return [
                self.violation(
                    f"plugins[{idx}].source: unknown source type '{source_type}' "
                    f"(known types: {', '.join(sorted(_SOURCE_REQUIRED_FIELDS))})",
                    file_path=marketplace_file,
                    severity=Severity.WARNING,
                )
            ]

        for required in _SOURCE_REQUIRED_FIELDS[source_type]:
            value = source.get(required)
            # ``None`` counts as absent: an explicit null is no more usable
            # than a missing key, and reporting it as present would let it
            # through every check below.
            if value is None:
                violations.append(
                    self.violation(
                        f"plugins[{idx}].source of type '{source_type}' requires "
                        f"a '{required}' field",
                        file_path=marketplace_file,
                    )
                )
            elif not isinstance(value, str) or not value:
                violations.append(
                    self.violation(
                        f"plugins[{idx}].source.{required} must be a non-empty string",
                        file_path=marketplace_file,
                    )
                )

        if source_type == "local" and isinstance(source.get("path"), str) and source["path"]:
            violations.extend(
                self._check_local_path(
                    source["path"], f"plugins[{idx}].source.path", marketplace_file
                )
            )

        if source_type == "npm":
            violations.extend(self._check_npm_registry(source, idx, marketplace_file))

        return violations

    def _check_local_path(
        self, value: str, label: str, marketplace_file: Path
    ) -> List[RuleViolation]:
        if not value:
            # "" resolves to the marketplace root, so nothing below rejects
            # it and an entry that can never install would pass as INFO.
            return [self.violation(f"{label} is an empty path", file_path=marketplace_file)]
        problem = path_problem(value, "marketplace root")
        if problem:
            return [self.violation(f"{label}: {problem}", file_path=marketplace_file)]
        if not value.startswith("./"):
            return [
                self.violation(
                    f"{label}: relative path '{value}' should start with './'",
                    file_path=marketplace_file,
                    severity=Severity.INFO,
                )
            ]
        return []

    def _check_npm_registry(
        self, source: dict, idx: int, marketplace_file: Path
    ) -> List[RuleViolation]:
        """`registry` "must be an HTTPS URL without embedded credentials, a
        query, or a fragment"."""
        registry = source.get("registry")
        if registry is None:
            return []
        if not isinstance(registry, str):
            return [
                self.violation(
                    f"plugins[{idx}].source.registry must be a string",
                    file_path=marketplace_file,
                )
            ]
        try:
            parsed = urlparse(registry)
        except ValueError:
            # urlparse raises on an unbalanced '[' ("Invalid IPv6 URL").
            # Letting it escape aborts the whole rule, so the credential and
            # scheme checks below would fail open on exactly the malformed
            # input they exist to catch.
            return [
                self.violation(
                    f"plugins[{idx}].source.registry '{registry}' is not a valid URL",
                    file_path=marketplace_file,
                )
            ]
        problems = []
        if parsed.scheme != "https":
            problems.append("must use https")
        if parsed.username or parsed.password:
            problems.append("must not embed credentials")
        if parsed.query:
            problems.append("must not have a query string")
        if parsed.fragment:
            problems.append("must not have a fragment")
        if not problems:
            return []
        return [
            self.violation(
                f"plugins[{idx}].source.registry '{registry}': " + ", ".join(problems),
                file_path=marketplace_file,
            )
        ]

    def _check_policy(self, policy: Any, idx: int, marketplace_file: Path) -> List[RuleViolation]:
        if policy is None:
            return []
        if not isinstance(policy, dict):
            return [
                self.violation(
                    f"plugins[{idx}].policy must be an object", file_path=marketplace_file
                )
            ]

        violations: List[RuleViolation] = []
        # Both value sets are open-ended upstream, so an unrecognized value
        # is a warning rather than an error and the sets are configurable.
        for field, default in (
            ("installation", DEFAULT_INSTALLATION_VALUES),
            ("authentication", DEFAULT_AUTHENTICATION_VALUES),
        ):
            value = policy.get(field)
            if value is None:
                violations.append(
                    self.violation(
                        f"plugins[{idx}].policy missing '{field}'",
                        file_path=marketplace_file,
                        severity=Severity.WARNING,
                    )
                )
                continue
            known = self.config.get(f"{field}-values", default)
            if value not in known:
                violations.append(
                    self.violation(
                        f"plugins[{idx}].policy.{field}: unrecognized value "
                        # str(): the config schema declares a list without an
                        # element type, so a user's non-string value must not
                        # crash the rule inside its own error message.
                        f"{value!r} (known values: {', '.join(str(v) for v in known)})",
                        file_path=marketplace_file,
                        severity=Severity.WARNING,
                    )
                )

        return violations

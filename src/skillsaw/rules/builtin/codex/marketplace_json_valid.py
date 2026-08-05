"""
Rule: codex-marketplace-json-valid
"""

import json
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext, codex_local_source_path
from skillsaw.diagnostics import safe_display
from skillsaw.lint_target import CodexMarketplaceConfigNode
from skillsaw.paths import safe_exists
from skillsaw.rules.builtin.utils import read_json

from ._helpers import (
    CODEX_MARKETPLACE_REPO_TYPES,
    KEBAB_CASE,
    nonfinite_constant_error,
    path_problem,
)

# Required fields per documented source type. Unknown types warn rather than
# error so a source type added upstream never breaks existing marketplaces.
_SOURCE_REQUIRED_FIELDS = {
    "local": ("path",),
    "url": ("url",),
    "git-subdir": ("url", "path"),
    "npm": ("package",),
}

# The upstream sources disagree on strictness: the prose spec hedges —
# "Use policy.installation values such as AVAILABLE, INSTALLED_BY_DEFAULT,
# or NOT_AVAILABLE" — while plugin-json-spec.md closes the same three as
# "Allowed values". A warning on an unrecognized value is the safe
# intersection, and the set is configurable.
DEFAULT_INSTALLATION_VALUES = ["AVAILABLE", "INSTALLED_BY_DEFAULT", "NOT_AVAILABLE"]

# Same split for policy.authentication: the prose spec describes the field,
# plugin-json-spec.md publishes exactly this pair as an enum. Unrecognized
# values warn for the same reason as installation.
DEFAULT_AUTHENTICATION_VALUES = ["ON_INSTALL", "ON_USE"]

# The docs mandate these on every entry ("Always include policy.installation,
# policy.authentication, and category on each plugin entry") but Codex still
# loads an entry without them, so their absence is a warning.
_RECOMMENDED_ENTRY_FIELDS = ("policy", "category")


def _source_identity(source: Any) -> str:
    """A comparable identity for an entry's source.

    ``./plugins/foo``, ``plugins/foo`` and ``{"source": "local", "path":
    "./plugins/foo"}`` all install the same directory, so local sources
    compare by normalised path — raw JSON comparison would report a
    duplicate name that is not one. Remote sources compare structurally.
    """
    local = codex_local_source_path(source)
    if local is not None:
        # One exact "./" prefix, not lstrip("./") — that strips an arbitrary
        # run of dots and slashes, so "./.plugins/foo" and "./plugins/foo"
        # would both reduce to "plugins/foo", suppressing a genuine conflict.
        normalised = PurePosixPath(local.replace("\\", "/")).as_posix()
        if normalised.startswith("./"):
            normalised = normalised[2:]
        return "local:" + normalised
    return json.dumps(source, sort_keys=True, default=str)


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
        # Shared across every catalog, not rebuilt per file: Codex aggregates
        # siblings into one namespace and ``skillsaw docs`` writes one page
        # per name, so two catalogs claiming a name can silently lose a page.
        # Maps a name to the (file, index, source) that claimed it first.
        seen_names: Dict[str, Tuple[Path, int, str]] = {}

        for node in context.lint_tree.find(CodexMarketplaceConfigNode):
            marketplace_file = node.path
            data, error = read_json(marketplace_file)
            if error:
                # An absent file (a --type-seeded node) is not a syntax
                # error — "Invalid JSON: Failed to read" would describe the
                # wrong defect.
                message = (
                    "Invalid JSON: {}".format(error)
                    if safe_exists(marketplace_file)
                    else "Marketplace file not found — Codex reads the catalog from this path"
                )
                violations.append(self.violation(message, file_path=marketplace_file))
                continue
            strict_error = nonfinite_constant_error(marketplace_file)
            if strict_error:
                violations.append(
                    self.violation(f"Invalid JSON: {strict_error}", file_path=marketplace_file)
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

            violations.extend(
                self._check_plugins(data, marketplace_file, context.root_path, seen_names)
            )

        return violations

    def _check_plugins(
        self,
        data: dict,
        marketplace_file: Path,
        root: Path,
        seen_names: Dict[str, Tuple[Path, int, str]],
    ) -> List[RuleViolation]:
        violations: List[RuleViolation] = []

        if "plugins" not in data:
            return [self.violation("Missing 'plugins' array", file_path=marketplace_file)]
        entries = data["plugins"]
        if not isinstance(entries, list):
            return [self.violation("'plugins' must be an array", file_path=marketplace_file)]

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
                violations.extend(self._check_source(entry["source"], idx, marketplace_file, root))

            for field in _RECOMMENDED_ENTRY_FIELDS:
                # ``None`` counts as absent throughout — an explicit null
                # carries no more information than a missing key.
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

            violations.extend(self._check_category(entry.get("category"), idx, marketplace_file))
            violations.extend(self._check_policy(entry.get("policy"), idx, marketplace_file))

        return violations

    def _check_category(
        self, category: Any, idx: int, marketplace_file: Path
    ) -> List[RuleViolation]:
        """A present ``category`` must be a non-empty string label.

        The set of labels is open-ended, so their *values* stay
        unconstrained — but ``""``, a number, or an array carries less
        information than an absent key, which already warns.
        """
        if category is None:
            return []  # absence already warned about above
        if not isinstance(category, str) or not category:
            return [
                self.violation(
                    f"plugins[{idx}] 'category' must be a non-empty string, got '{safe_display(category)}'",
                    file_path=marketplace_file,
                    severity=Severity.WARNING,
                )
            ]
        return []

    def _check_entry_name(
        self,
        entry: dict,
        idx: int,
        marketplace_file: Path,
        seen_names: Dict[str, Tuple[Path, int, str]],
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
                    f"plugins[{idx}] plugin name must be a string, got '{safe_display(name)}'",
                    file_path=marketplace_file,
                )
            ]
        if not name:
            # An empty identifier is a missing one — it must not stop at
            # the kebab-case warning.
            return [
                self.violation(
                    f"plugins[{idx}] required field 'name' is an empty string",
                    file_path=marketplace_file,
                )
            ]
        # A duplicate falls through to the casing check rather than
        # returning: two entries named ``Bad_Name`` have both defects.
        violations: List[RuleViolation] = []
        source_key = _source_identity(entry.get("source"))
        first = seen_names.get(name)
        # Across catalogs, one name pointing at one source is a curated
        # second listing, not a defect. It is only ambiguous when the two
        # entries resolve somewhere different — then Codex's aggregation
        # has to pick one and ``docs`` loses a page. Within a single file
        # any repeat is a defect.
        if first is not None and (first[0] == marketplace_file or first[2] != source_key):
            first_file, first_idx, _ = first
            # Name the file only when it differs.
            where = (
                f"plugins[{first_idx}]"
                if first_file == marketplace_file
                else f"{first_file.name} plugins[{first_idx}]"
            )
            violations.append(
                self.violation(
                    f"plugins[{idx}] duplicate plugin name '{safe_display(name)}' "
                    f"(first defined at {where})",
                    file_path=marketplace_file,
                )
            )
        elif first is None:
            seen_names[name] = (marketplace_file, idx, source_key)
        if not KEBAB_CASE.match(name):
            violations.append(
                self.violation(
                    f"plugins[{idx}] plugin name '{safe_display(name)}' should use kebab-case",
                    file_path=marketplace_file,
                    severity=Severity.WARNING,
                )
            )
        return violations

    def _check_source(
        self, source: Any, idx: int, marketplace_file: Path, root: Path
    ) -> List[RuleViolation]:
        """Validate an entry's source (bare local path string or typed object)."""
        violations: List[RuleViolation] = []

        if isinstance(source, str):
            # "For local entries, source can also be a plain string path."
            violations.extend(
                self._check_local_path(source, f"plugins[{idx}].source", marketplace_file, root)
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
        # An empty discriminator is missing, not unknown: it must not fall
        # through to the forward-compatibility warning and pass a default
        # ``fail-on: error``.
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
                    f"plugins[{idx}].source: unknown source type '{safe_display(source_type)}' "
                    f"(known types: {', '.join(sorted(_SOURCE_REQUIRED_FIELDS))})",
                    file_path=marketplace_file,
                    severity=Severity.WARNING,
                )
            ]

        for required in _SOURCE_REQUIRED_FIELDS[source_type]:
            value = source.get(required)
            # ``None`` counts as absent, as above.
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
                    source["path"], f"plugins[{idx}].source.path", marketplace_file, root
                )
            )

        if source_type == "npm":
            violations.extend(self._check_npm_registry(source, idx, marketplace_file))

        return violations

    def _check_local_path(
        self, value: str, label: str, marketplace_file: Path, root: Path
    ) -> List[RuleViolation]:
        if not value:
            # "" resolves to the marketplace root, so nothing below rejects
            # it and an entry that can never install would pass as INFO.
            return [self.violation(f"{label} is an empty path", file_path=marketplace_file)]
        problem = path_problem(value, "marketplace root", root)
        if problem:
            return [self.violation(f"{label}: {problem}", file_path=marketplace_file)]
        if not value.startswith("./"):
            return [
                self.violation(
                    f"{label}: relative path '{safe_display(value)}' should start with './'",
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
                    f"plugins[{idx}].source.registry is not a valid URL",
                    file_path=marketplace_file,
                )
            ]
        problems = []
        if parsed.scheme != "https":
            problems.append("must use https")
        try:
            hostname = parsed.hostname
        except ValueError:
            # A bracketed authority that survives urlparse can still fail
            # when the host is decoded (e.g. "https://[::1"). Same reasoning
            # as above: a raised exception here would abort the rule.
            hostname = None
        if not hostname:
            # "https:registry.example.com" and "https:///registry" both parse
            # with the right scheme and no host at all, so every other check
            # here passes on a URL that can never be fetched.
            problems.append("must name a host")
        try:
            parsed.port
        except ValueError:
            # ":not-a-port" and ":99999" reach here with a valid scheme and
            # host. The port is only decoded on access, so nothing else in
            # this check would ever look at it.
            problems.append("has an invalid port")
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
                f"plugins[{idx}].source.registry: " + ", ".join(problems),
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
            if not isinstance(known, (list, tuple, set)):
                # ``value not in known`` raises TypeError on a non-iterable
                # — a rule crash that leaves the rest of the catalog
                # unvalidated.
                known = default
            if value not in known:
                violations.append(
                    self.violation(
                        f"plugins[{idx}].policy.{field}: unrecognized value "
                        # str(): the config schema declares a list without an
                        # element type, so a user's non-string value must not
                        # crash the rule inside its own error message.
                        f"'{safe_display(value)}' (known values: {', '.join(str(v) for v in known)})",
                        file_path=marketplace_file,
                        severity=Severity.WARNING,
                    )
                )

        return violations

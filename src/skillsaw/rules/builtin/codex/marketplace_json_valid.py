"""Rule: codex-marketplace-json-valid."""

from pathlib import Path
import re
from typing import List
from urllib.parse import urlparse

from skillsaw.context import RepositoryContext
from skillsaw.lint_target import CodexMarketplaceConfigNode
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.rules.builtin.utils import read_json

from ._helpers import CODEX_MARKETPLACE_REPO_TYPES, KEBAB_CASE, relative_path_error

_INSTALLATION_VALUES = {"AVAILABLE", "INSTALLED_BY_DEFAULT", "NOT_AVAILABLE"}
_REMOTE_SOURCE_FIELDS = {
    "url": ("url",),
    "git-subdir": ("url", "path"),
    "npm": ("package",),
}
_SCP_GIT_URL = re.compile(r"^[^/@\s]+@[^:\s]+:.+$")


class CodexMarketplaceJsonValidRule(Rule):
    """Validate Codex marketplace catalogs and their source policies."""

    repo_types = CODEX_MARKETPLACE_REPO_TYPES

    @property
    def rule_id(self) -> str:
        return "codex-marketplace-json-valid"

    @property
    def description(self) -> str:
        return "Codex marketplace.json must follow the documented catalog format"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        nodes = context.lint_tree.find(CodexMarketplaceConfigNode)
        if not nodes:
            return [
                self.violation(
                    "Codex marketplace file not found",
                    file_path=context.root_path / ".agents" / "plugins" / "marketplace.json",
                )
            ]

        marketplace_file = nodes[0].path
        data, error = read_json(marketplace_file)
        if error:
            return [self.violation(f"Invalid JSON: {error}", file_path=marketplace_file)]
        if not isinstance(data, dict):
            return [
                self.violation(
                    "Marketplace file must contain a JSON object", file_path=marketplace_file
                )
            ]

        violations = self._check_header(data, marketplace_file)
        plugins = data.get("plugins")
        if not isinstance(plugins, list):
            violations.append(
                self.violation("Missing or invalid 'plugins' array", file_path=marketplace_file)
            )
            return violations

        seen_names: dict[str, int] = {}
        for idx, entry in enumerate(plugins):
            violations.extend(self._check_entry(entry, idx, seen_names, marketplace_file))
        return violations

    def _check_header(self, data: dict, marketplace_file: Path) -> List[RuleViolation]:
        violations = []
        name = data.get("name")
        if not isinstance(name, str) or not name:
            violations.append(
                self.violation("Missing or invalid 'name' field", file_path=marketplace_file)
            )
        elif not KEBAB_CASE.fullmatch(name):
            violations.append(
                self.violation("Marketplace name must use kebab-case", file_path=marketplace_file)
            )

        interface = data.get("interface")
        if interface is not None:
            if not isinstance(interface, dict):
                violations.append(
                    self.violation("'interface' must be an object", file_path=marketplace_file)
                )
            elif "displayName" in interface and not isinstance(interface["displayName"], str):
                violations.append(
                    self.violation(
                        "interface.displayName must be a string", file_path=marketplace_file
                    )
                )
        return violations

    def _check_entry(
        self,
        entry: object,
        idx: int,
        seen_names: dict[str, int],
        marketplace_file: Path,
    ) -> List[RuleViolation]:
        if not isinstance(entry, dict):
            return [self.violation(f"plugins[{idx}] must be an object", file_path=marketplace_file)]

        violations = []
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            violations.append(
                self.violation(
                    f"plugins[{idx}] missing or invalid 'name'", file_path=marketplace_file
                )
            )
        else:
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
                    f"plugins[{idx}] missing required 'source'", file_path=marketplace_file
                )
            )
        else:
            violations.extend(self._check_source(entry["source"], idx, marketplace_file))

        policy = entry.get("policy")
        if not isinstance(policy, dict):
            violations.append(
                self.violation(
                    f"plugins[{idx}] missing or invalid 'policy' object",
                    file_path=marketplace_file,
                )
            )
        else:
            installation = policy.get("installation")
            if installation not in _INSTALLATION_VALUES:
                violations.append(
                    self.violation(
                        f"plugins[{idx}].policy.installation must be one of: "
                        f"{', '.join(sorted(_INSTALLATION_VALUES))}",
                        file_path=marketplace_file,
                    )
                )
            authentication = policy.get("authentication")
            if not isinstance(authentication, str) or not authentication:
                violations.append(
                    self.violation(
                        f"plugins[{idx}].policy.authentication must be a non-empty string",
                        file_path=marketplace_file,
                    )
                )

        if not isinstance(entry.get("category"), str) or not entry.get("category"):
            violations.append(
                self.violation(
                    f"plugins[{idx}] missing or invalid 'category'", file_path=marketplace_file
                )
            )
        return violations

    def _check_source(
        self, source: object, idx: int, marketplace_file: Path
    ) -> List[RuleViolation]:
        label = f"plugins[{idx}].source"
        if isinstance(source, str):
            error = relative_path_error(source)
            return [self.violation(f"{label} {error}", file_path=marketplace_file)] if error else []
        if not isinstance(source, dict):
            return [
                self.violation(
                    f"{label} must be a local path string or source object",
                    file_path=marketplace_file,
                )
            ]

        source_type = source.get("source")
        if source_type == "local":
            error = relative_path_error(source.get("path"))
            return (
                [self.violation(f"{label}.path {error}", file_path=marketplace_file)]
                if error
                else []
            )
        if not isinstance(source_type, str) or not source_type:
            return [
                self.violation(
                    f"{label} object missing required 'source' type",
                    file_path=marketplace_file,
                )
            ]
        if source_type not in _REMOTE_SOURCE_FIELDS:
            return [
                self.violation(
                    f"{label} has unknown source type '{source_type}'",
                    file_path=marketplace_file,
                    severity=Severity.WARNING,
                )
            ]

        violations = []
        for field in _REMOTE_SOURCE_FIELDS[source_type]:
            if not isinstance(source.get(field), str) or not source[field]:
                violations.append(
                    self.violation(
                        f"{label} of type '{source_type}' requires a non-empty '{field}'",
                        file_path=marketplace_file,
                    )
                )
        if source_type == "git-subdir" and isinstance(source.get("path"), str):
            error = relative_path_error(source["path"])
            if error:
                violations.append(
                    self.violation(f"{label}.path {error}", file_path=marketplace_file)
                )
        if source_type in {"url", "git-subdir"} and isinstance(source.get("url"), str):
            parsed = urlparse(source["url"])
            is_url = parsed.scheme in {"http", "https", "ssh", "git"} and bool(parsed.netloc)
            if not is_url and not _SCP_GIT_URL.fullmatch(source["url"]):
                violations.append(
                    self.violation(
                        f"{label}.url must be a supported Git URL", file_path=marketplace_file
                    )
                )
        if source_type == "npm":
            violations.extend(self._check_npm_source(source, label, marketplace_file))
        for selector in ("ref", "sha"):
            if selector in source and not isinstance(source[selector], str):
                violations.append(
                    self.violation(
                        f"{label}.{selector} must be a string", file_path=marketplace_file
                    )
                )
        return violations

    def _check_npm_source(
        self, source: dict, label: str, marketplace_file: Path
    ) -> List[RuleViolation]:
        violations = []
        version = source.get("version")
        if version is not None and (
            not isinstance(version, str)
            or version.startswith(("./", "../", "/"))
            or "://" in version
        ):
            violations.append(
                self.violation(
                    f"{label}.version must be a package version, tag, or range",
                    file_path=marketplace_file,
                )
            )
        registry = source.get("registry")
        if registry is not None:
            parsed = urlparse(registry) if isinstance(registry, str) else None
            if (
                parsed is None
                or parsed.scheme != "https"
                or not parsed.netloc
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
            ):
                violations.append(
                    self.violation(
                        f"{label}.registry must be an HTTPS URL without credentials, "
                        "query, or fragment",
                        file_path=marketplace_file,
                    )
                )
        return violations

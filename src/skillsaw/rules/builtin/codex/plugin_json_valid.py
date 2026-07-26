"""Rule: codex-plugin-json-valid."""

from pathlib import Path
from typing import List
from urllib.parse import urlparse

from skillsaw.context import RepositoryContext
from skillsaw.lint_target import CodexPluginNode
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.rules.builtin.utils import read_json

from ._helpers import CODEX_PLUGIN_REPO_TYPES, KEBAB_CASE, SEMVER, relative_path_error

_COMPONENT_FIELDS = ("skills", "mcpServers", "apps")
_INTERFACE_STRING_FIELDS = (
    "displayName",
    "shortDescription",
    "longDescription",
    "developerName",
    "category",
)
_INTERFACE_URL_FIELDS = ("websiteURL", "privacyPolicyURL", "termsOfServiceURL")
_INTERFACE_PATH_FIELDS = ("composerIcon", "logo")


class CodexPluginJsonValidRule(Rule):
    """Validate Codex plugin identity, component paths, and interface metadata."""

    repo_types = CODEX_PLUGIN_REPO_TYPES

    @property
    def rule_id(self) -> str:
        return "codex-plugin-json-valid"

    @property
    def description(self) -> str:
        return "Codex plugin.json must follow the documented manifest format"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        for plugin_node in context.lint_tree.find(CodexPluginNode):
            manifest = plugin_node.path / ".codex-plugin" / "plugin.json"
            if not manifest.is_file():
                continue
            data, error = read_json(manifest)
            if error:
                violations.append(self.violation(f"Invalid JSON: {error}", file_path=manifest))
                continue
            if not isinstance(data, dict):
                violations.append(
                    self.violation("Expected JSON object in plugin.json", file_path=manifest)
                )
                continue

            violations.extend(self._check_identity(data, manifest))
            violations.extend(self._check_components(data, plugin_node.path, manifest))
            violations.extend(
                self._check_interface(data.get("interface"), plugin_node.path, manifest)
            )
        return violations

    def _check_identity(self, data: dict, manifest: Path) -> List[RuleViolation]:
        violations = []
        for field in ("name", "version", "description"):
            value = data.get(field)
            if not isinstance(value, str) or not value.strip():
                violations.append(
                    self.violation(
                        f"Missing or invalid required field '{field}'", file_path=manifest
                    )
                )

        name = data.get("name")
        if isinstance(name, str) and name and not KEBAB_CASE.fullmatch(name):
            violations.append(self.violation("Plugin name must use kebab-case", file_path=manifest))
        version = data.get("version")
        if isinstance(version, str) and version and not SEMVER.fullmatch(version):
            violations.append(
                self.violation(
                    f"Version '{version}' should follow semver (X.Y.Z)", file_path=manifest
                )
            )
        author = data.get("author")
        if author is not None and (
            not isinstance(author, dict)
            or not isinstance(author.get("name"), str)
            or not author["name"].strip()
        ):
            violations.append(
                self.violation(
                    "Author must be an object with a non-empty 'name'", file_path=manifest
                )
            )
        return violations

    def _check_components(
        self, data: dict, plugin_root: Path, manifest: Path
    ) -> List[RuleViolation]:
        violations = []
        for field in _COMPONENT_FIELDS:
            if field not in data:
                continue
            violations.extend(
                self._check_path(data[field], field, plugin_root, manifest, require_exists=True)
            )

        hooks = data.get("hooks")
        if isinstance(hooks, str):
            violations.extend(
                self._check_path(hooks, "hooks", plugin_root, manifest, require_exists=True)
            )
        elif isinstance(hooks, list):
            for idx, value in enumerate(hooks):
                if isinstance(value, str):
                    violations.extend(
                        self._check_path(
                            value,
                            f"hooks[{idx}]",
                            plugin_root,
                            manifest,
                            require_exists=True,
                        )
                    )
                elif not isinstance(value, dict):
                    violations.append(
                        self.violation(
                            f"hooks[{idx}] must be a path or inline hooks object",
                            file_path=manifest,
                        )
                    )
        elif hooks is not None and not isinstance(hooks, dict):
            violations.append(
                self.violation(
                    "'hooks' must be a path, path array, or inline hooks object",
                    file_path=manifest,
                )
            )
        return violations

    def _check_interface(
        self, interface: object, plugin_root: Path, manifest: Path
    ) -> List[RuleViolation]:
        if interface is None:
            return []
        if not isinstance(interface, dict):
            return [self.violation("'interface' must be an object", file_path=manifest)]

        violations = []
        for field in _INTERFACE_STRING_FIELDS:
            if field in interface and not isinstance(interface[field], str):
                violations.append(
                    self.violation(f"interface.{field} must be a string", file_path=manifest)
                )
        for field in _INTERFACE_URL_FIELDS:
            value = interface.get(field)
            if value is not None and (
                not isinstance(value, str) or urlparse(value).scheme not in {"http", "https"}
            ):
                violations.append(
                    self.violation(f"interface.{field} must be an HTTP(S) URL", file_path=manifest)
                )
        for field in _INTERFACE_PATH_FIELDS:
            if field in interface:
                violations.extend(
                    self._check_path(
                        interface[field],
                        f"interface.{field}",
                        plugin_root,
                        manifest,
                        require_exists=True,
                    )
                )
        screenshots = interface.get("screenshots")
        if screenshots is not None:
            if not isinstance(screenshots, list):
                violations.append(
                    self.violation("interface.screenshots must be an array", file_path=manifest)
                )
            else:
                for idx, value in enumerate(screenshots):
                    violations.extend(
                        self._check_path(
                            value,
                            f"interface.screenshots[{idx}]",
                            plugin_root,
                            manifest,
                            require_exists=True,
                        )
                    )
        capabilities = interface.get("capabilities")
        if capabilities is not None and (
            not isinstance(capabilities, list)
            or any(not isinstance(value, str) for value in capabilities)
        ):
            violations.append(
                self.violation(
                    "interface.capabilities must be an array of strings", file_path=manifest
                )
            )
        prompts = interface.get("defaultPrompt")
        if prompts is not None and (
            not isinstance(prompts, list) or any(not isinstance(value, str) for value in prompts)
        ):
            violations.append(
                self.violation(
                    "interface.defaultPrompt must be an array of strings", file_path=manifest
                )
            )
        return violations

    def _check_path(
        self,
        value: object,
        label: str,
        plugin_root: Path,
        manifest: Path,
        *,
        require_exists: bool,
    ) -> List[RuleViolation]:
        error = relative_path_error(value)
        if error:
            return [self.violation(f"{label} {error}", file_path=manifest)]
        assert isinstance(value, str)
        if require_exists and not (plugin_root / value).exists():
            return [self.violation(f"{label} points to missing path '{value}'", file_path=manifest)]
        return []

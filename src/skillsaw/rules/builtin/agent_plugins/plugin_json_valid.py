"""Rule: agent-plugin-json-valid."""

from __future__ import annotations

from pathlib import Path
from typing import List

from skillsaw.context import RepositoryContext
from skillsaw.diagnostics import safe_display
from skillsaw.formats.agent_plugins import (
    SUPPORTED_AGENT_PLUGIN_SCHEMA_VERSIONS,
    agent_plugin_schema_id,
    agent_plugin_schema_version,
    supported_agent_plugin_schema_version,
)
from skillsaw.lint_target import AgentPluginConfigNode
from skillsaw.paths import (
    contained_resolve,
    safe_exists,
    safe_is_dir,
    safe_is_file,
    safe_is_symlink,
    safe_resolve,
)
from skillsaw.rule import Rule, RuleViolation, Severity

from ._helpers import (
    AGENT_PLUGIN_REPO_TYPES,
    MANIFEST_FIELDS,
    PLUGIN_VALIDATORS,
    schema_error_summary,
    stable_key,
    strict_json,
)

_SUPPORTED_VERSIONS_TEXT = " and ".join(SUPPORTED_AGENT_PLUGIN_SCHEMA_VERSIONS)


class AgentPluginJsonValidRule(Rule):
    """Validate the portable manifest and fixed skills component location."""

    repo_types = AGENT_PLUGIN_REPO_TYPES
    since = "0.18.0"

    @property
    def rule_id(self) -> str:
        return "agent-plugin-json-valid"

    @property
    def description(self) -> str:
        return "Agent Plugins plugin.json and skills location must conform to a supported schema"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        # The node itself is the format gate. Do not provenance-filter this:
        # ``--type agent-plugin`` must validate a missing manifest even when
        # another ecosystem also claims the directory.
        for node in context.lint_tree.find(AgentPluginConfigNode):
            violations.extend(self._check_package(node))
        return violations

    def _check_package(self, node: AgentPluginConfigNode) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        plugin_root = safe_resolve(node.plugin_dir)
        manifest = node.path
        if plugin_root is None:
            return [
                self.violation(
                    "Plugin root cannot be resolved safely",
                    file_path=manifest,
                    fingerprint_discriminator="manifest:root-unresolved",
                )
            ]

        if not (safe_exists(manifest) or safe_is_symlink(manifest)):
            violations.append(
                self.violation(
                    "Missing plugin.json at the Agent Plugin root",
                    file_path=manifest,
                    fingerprint_discriminator="manifest:missing",
                )
            )
        else:
            resolved_manifest = contained_resolve(manifest, plugin_root)
            if resolved_manifest is None:
                violations.append(
                    self.violation(
                        "plugin.json must resolve within the plugin root",
                        file_path=manifest,
                        fingerprint_discriminator="manifest:escape",
                    )
                )
            elif not safe_is_file(resolved_manifest):
                violations.append(
                    self.violation(
                        "plugin.json must resolve to a regular file",
                        file_path=manifest,
                        fingerprint_discriminator="manifest:not-file",
                    )
                )
            else:
                violations.extend(self._check_manifest_json(manifest))

        # Component-location failures are deliberately independent: a bad
        # skills component must not hide a valid MCP component (and vice versa).
        violations.extend(self._check_skills(node.plugin_dir, plugin_root))
        return violations

    def _check_manifest_json(self, manifest: Path) -> List[RuleViolation]:
        data, error = strict_json(manifest)
        if error:
            return [
                self.violation(
                    f"Invalid JSON: {error}",
                    file_path=manifest,
                    fingerprint_discriminator="manifest:json",
                )
            ]
        if not isinstance(data, dict):
            return [
                self.violation(
                    "plugin.json must contain a JSON object",
                    file_path=manifest,
                    fingerprint_discriminator="manifest:not-object",
                )
            ]

        violations: List[RuleViolation] = []
        unknown = sorted(set(data) - MANIFEST_FIELDS)
        for field in unknown:
            violations.append(
                self.violation(
                    f"Unknown top-level field '{safe_display(field)}' is ignored by Agent Plugins",
                    file_path=manifest,
                    severity=Severity.WARNING,
                    fingerprint_discriminator=f"manifest:unknown:{stable_key(field)}",
                )
            )

        # The spec makes these two schema failures non-fatal. Validate a
        # sanitized view so they are reported once at warning severity while
        # all other schema failures remain fatal errors.
        checked = {key: value for key, value in data.items() if key in MANIFEST_FIELDS}
        declared_schema = checked.get("$schema")
        schema_version = supported_agent_plugin_schema_version(declared_schema, "plugin")
        if "$schema" in checked and schema_version is None:
            version = agent_plugin_schema_version(declared_schema, "plugin")
            message = (
                f"Unsupported Agent Plugins manifest schema version "
                f"'{safe_display(version)}'; this skillsaw release supports "
                f"{_SUPPORTED_VERSIONS_TEXT}"
                if version is not None
                else (
                    "'$schema' must be a canonical supported Agent Plugins "
                    "plugin schema identifier"
                )
            )
            violations.append(
                self.violation(
                    message,
                    file_path=manifest,
                    fingerprint_discriminator="manifest:schema-version",
                )
            )
            # Suppress the schema's duplicate const error. The dedicated
            # diagnostic above remains fatal and is clearer about support.
            schema_version = SUPPORTED_AGENT_PLUGIN_SCHEMA_VERSIONS[0]
            checked["$schema"] = agent_plugin_schema_id(schema_version, "plugin")
        if "extensions" in checked and not isinstance(checked["extensions"], dict):
            violations.append(
                self.violation(
                    "Non-object 'extensions' is ignored by Agent Plugins",
                    file_path=manifest,
                    severity=Severity.WARNING,
                    fingerprint_discriminator="manifest:extensions-not-object",
                )
            )
            checked.pop("extensions")

        validator = PLUGIN_VALIDATORS[schema_version or SUPPORTED_AGENT_PLUGIN_SCHEMA_VERSIONS[0]]
        schema_errors = list(validator.iter_errors(checked))
        if schema_errors:
            violations.append(
                self.violation(
                    f"plugin.json does not conform to Agent Plugins "
                    f"{schema_version or _SUPPORTED_VERSIONS_TEXT}: "
                    f"{schema_error_summary(schema_errors)}",
                    file_path=manifest,
                    fingerprint_discriminator="manifest:schema",
                )
            )
        return violations

    def _check_skills(self, plugin_dir: Path, plugin_root: Path) -> List[RuleViolation]:
        skills = plugin_dir / "skills"
        if not (safe_exists(skills) or safe_is_symlink(skills)):
            return []
        resolved_skills = contained_resolve(skills, plugin_root)
        if resolved_skills is None:
            return [
                self.violation(
                    "skills/ must resolve within the plugin root",
                    file_path=skills,
                    fingerprint_discriminator="skills:escape",
                )
            ]
        if not safe_is_dir(resolved_skills):
            return [
                self.violation(
                    "skills/ must resolve to a directory",
                    file_path=skills,
                    fingerprint_discriminator="skills:not-directory",
                )
            ]

        violations: List[RuleViolation] = []
        try:
            children = sorted(skills.iterdir())
        except OSError as error:
            return [
                self.violation(
                    f"Could not inspect skills/: {safe_display(error)}",
                    file_path=skills,
                    fingerprint_discriminator="skills:unreadable",
                )
            ]

        for child in children:
            resolved_child = contained_resolve(child, plugin_root)
            if resolved_child is None:
                if safe_is_dir(child) or safe_is_symlink(child):
                    violations.append(
                        self.violation(
                            f"Skill entry '{safe_display(child.name)}' resolves outside the plugin root",
                            file_path=child,
                            fingerprint_discriminator=f"skill:{stable_key(child.name)}:escape",
                        )
                    )
                continue
            if not safe_is_dir(resolved_child):
                continue
            entrypoint = child / "SKILL.md"
            if not (safe_exists(entrypoint) or safe_is_symlink(entrypoint)):
                continue
            resolved_entrypoint = contained_resolve(entrypoint, plugin_root)
            if resolved_entrypoint is None:
                violations.append(
                    self.violation(
                        f"{safe_display(child.name)}/SKILL.md resolves outside the plugin root",
                        file_path=entrypoint,
                        fingerprint_discriminator=(
                            f"skill:{stable_key(child.name)}:entrypoint-escape"
                        ),
                    )
                )
            elif not safe_is_file(resolved_entrypoint):
                violations.append(
                    self.violation(
                        f"{safe_display(child.name)}/SKILL.md must resolve to a regular file",
                        file_path=entrypoint,
                        fingerprint_discriminator=(
                            f"skill:{stable_key(child.name)}:entrypoint-not-file"
                        ),
                    )
                )
        return violations

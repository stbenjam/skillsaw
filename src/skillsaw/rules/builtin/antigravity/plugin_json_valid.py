"""Rule: antigravity-plugin-json-valid."""

from __future__ import annotations

from typing import List

from skillsaw.context import RepositoryContext
from skillsaw.diagnostics import safe_display
from skillsaw.formats.antigravity import PLUGIN_MESSAGE_FIELDS, PLUGIN_NAME_RE
from skillsaw.lint_target import AntigravityPluginConfigNode
from skillsaw.paths import safe_exists, safe_is_file, safe_is_symlink
from skillsaw.repository_types import RepositoryType
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.utils import read_json_strict


class AntigravityPluginJsonValidRule(Rule):
    """Validate an Antigravity plugin manifest.

    ``plugin.json`` is the marker: ``agy`` loads a directory under
    ``plugins/`` as a plugin only when the manifest parses. So a defect
    here is not a quality problem, it is "this directory is not a plugin",
    and the whole tree below it — skills, agents, hooks, MCP servers — goes
    unloaded. That is what puts the parse and type failures at ERROR.

    The manifest is a protojson message with four fields. Every other key,
    ``$schema`` and ``version`` and ``author`` included, is discarded as
    unknown and the plugin still loads, so none of them is reported.

    The vendor publishes a schema for it inline under "Full JSON Schema" at
    https://antigravity.google/docs/cli/plugins/ — ``name`` required with
    pattern ``^[a-zA-Z0-9-_]+$``, ``description`` optional,
    ``additionalProperties: false``. The checks below follow the *loader*
    rather than that schema, because the two disagree and the loader is
    what decides whether the directory is a plugin: ``disabled`` and
    ``logo`` load and are absent from the schema, and a key the schema
    forbids is discarded rather than refused. The one place the schema
    still speaks is the message for a missing ``name``, which says the
    published schema requires it.
    """

    since = "0.20.0"
    # ``enabled: auto`` on the base default, gated on the two places these
    # manifests live: an Antigravity workspace and an Antigravity plugin.
    repo_types = frozenset({RepositoryType.ANTIGRAVITY, RepositoryType.ANTIGRAVITY_PLUGIN})

    @property
    def rule_id(self) -> str:
        return "antigravity-plugin-json-valid"

    @property
    def description(self) -> str:
        return "plugin.json must parse as an Antigravity manifest with correctly typed fields"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        # The node itself is the format gate — no ``provenance_scope``, so a
        # forced ``--type antigravity-plugin`` still reports a directory
        # that carries no manifest at all.
        for node in context.lint_tree.find(AntigravityPluginConfigNode):
            violations.extend(
                self._check_manifest(
                    node,
                    dual_claimed=context.provenance(node.plugin_dir).agent_plugin,
                )
            )
        return violations

    def _check_manifest(
        self, node: AntigravityPluginConfigNode, *, dual_claimed: bool = False
    ) -> List[RuleViolation]:
        manifest = node.path
        if not safe_is_file(manifest):
            problem = (
                "plugin.json is not a regular file"
                if (safe_exists(manifest) or safe_is_symlink(manifest))
                else "plugin.json is missing"
            )
            return [
                self.violation(
                    f"{problem}; Antigravity loads a directory as a plugin only when it "
                    "carries a parseable manifest",
                    file_path=manifest,
                    fingerprint_discriminator="manifest-unreadable",
                )
            ]

        # Strict: a repeated key is a ``proto: duplicate field`` error for
        # Antigravity, where a lenient reader would keep the last one and
        # report the file clean.
        data, error = read_json_strict(manifest)
        if error:
            return [
                self.violation(
                    f"plugin.json does not parse, so the directory is not a plugin: "
                    f"{safe_display(error)}",
                    file_path=manifest,
                    fingerprint_discriminator="parse-error",
                )
            ]
        if not isinstance(data, dict):
            return [
                self.violation(
                    "plugin.json must be a JSON object, so the directory is not a plugin",
                    file_path=manifest,
                    fingerprint_discriminator="root-not-object",
                )
            ]

        violations: List[RuleViolation] = []
        for field, python_type, label in PLUGIN_MESSAGE_FIELDS:
            value = data.get(field)
            # Measured: protojson takes ``null`` as the field's default, so
            # ``{"name": null}`` is "missing name" and ``{"disabled": null}``
            # validates clean. A null is the key's absence, never a type
            # error.
            if value is None:
                continue
            if python_type is bool:
                well_typed = isinstance(value, bool)
            else:
                well_typed = isinstance(value, python_type) and not isinstance(value, bool)
            if not well_typed:
                violations.append(
                    self.violation(
                        f"'{field}' must be a {label}",
                        file_path=manifest,
                        fingerprint_discriminator=f"field:{field}",
                    )
                )

        name = data.get("name")
        # ``null``, ``""`` and an absent key are one case: all three are
        # protojson's default for a string field, all three report
        # ``missing name``, and all three fall back to the directory name
        # (measured). One finding, and never the charset one — an empty
        # name is not a name the author chose badly.
        if name is None or name == "":
            violations.append(
                self.violation(
                    "'name' is absent; the published manifest schema requires it, "
                    "discovery falls back to the directory name, and "
                    "'agy plugin install' refuses the plugin",
                    file_path=manifest,
                    severity=Severity.INFO,
                    fingerprint_discriminator="name-absent",
                )
            )
        # Not on a directory Agent Plugins also claims: that grammar permits
        # a dot, so warning that ``acme.tools`` is uninstallable addresses
        # the wrong author — the name is correct for the format the manifest
        # was written in, and the directory declares itself to both.
        elif isinstance(name, str) and not dual_claimed and not PLUGIN_NAME_RE.fullmatch(name):
            violations.append(
                self.violation(
                    f"plugin name '{safe_display(name)}' is not installable; "
                    "'agy plugin install' accepts letters, digits, '-' and '_' only",
                    file_path=manifest,
                    severity=Severity.WARNING,
                    fingerprint_discriminator="name-charset",
                )
            )
        return violations

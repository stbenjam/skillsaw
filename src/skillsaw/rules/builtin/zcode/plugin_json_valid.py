"""
Rule: zcode-plugin-json-valid

Checks a ``.zcode-plugin/plugin.json`` the way ZCode's plugin loader reads
it: a JSON object with a valid ``name``, component paths that stay inside
the plugin, manifest-declared commands ZCode can materialize, and no
components ZCode ignores.
"""

from typing import Any, Dict, List

from skillsaw.context import RepositoryContext
from skillsaw.formats import zcode
from skillsaw.lint_target import ZCodePluginConfigNode
from skillsaw.diagnostics import safe_display
from skillsaw.paths import contained_resolve, safe_exists, safe_is_file, safe_resolve
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.utils import read_json_strict

from ._helpers import ZCODE_PLUGIN_REPO_TYPES


class ZCodePluginJsonValidRule(Rule):
    """Check that a ZCode plugin manifest loads"""

    since = "0.23.0"

    repo_types = ZCODE_PLUGIN_REPO_TYPES

    @property
    def rule_id(self) -> str:
        return "zcode-plugin-json-valid"

    @property
    def description(self) -> str:
        return "A .zcode-plugin/plugin.json must be a manifest ZCode's loader accepts"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        # A catalog-listed directory without a manifest is the catalog rule's
        # finding: it names the entry, and ``strict: false`` excuses it.
        listed = set(context.zcode_listed_source_dirs())
        # A ``.zcode-plugin`` (or its manifest) symlinked out of the plugin
        # claims nothing, so no node exists for it; ZCode still follows the
        # link and loads the manifest, inline hooks and servers included.
        for marker in context.agent_tool_dirs(zcode.PLUGIN_DIR_NAME):
            if zcode.zcode_marker_escapes(marker.parent):
                violations.append(
                    self.violation(
                        f"{zcode.PLUGIN_DIR_NAME} is a symlink out of the plugin: ZCode loads "
                        "the manifest it points to, but skillsaw cannot lint it or anything it "
                        "declares. Commit the manifest inside the plugin",
                        marker,
                    )
                )
        for node in context.lint_tree.find(ZCodePluginConfigNode):
            # Only ZCode's own spelling. A Claude or Codex manifest ZCode
            # falls back to is that ecosystem's file, and its rules own it.
            if node.path.parent.name != zcode.PLUGIN_DIR_NAME:
                continue
            if safe_is_file(node.path):
                violations.extend(self._check_manifest(node))
            elif safe_exists(node.path):
                violations.append(
                    self.violation(
                        "plugin.json is not a regular file; ZCode skips this plugin", node.path
                    )
                )
            elif safe_resolve(node.plugin_dir) not in listed:
                # Reached under a forced ``--type zcode-plugin``: ZCode
                # refuses a plugin with no manifest (``plugin_manifest_not_found``).
                violations.append(
                    self.violation(
                        "No .zcode-plugin/plugin.json (or Claude or Codex manifest); "
                        "ZCode skips this plugin",
                        node.path,
                    )
                )
        return violations

    def _check_manifest(self, node: ZCodePluginConfigNode) -> List[RuleViolation]:
        path = node.path
        # ``JSON.parse``: non-finite tokens are syntax errors, repeated keys are not.
        data, error = read_json_strict(path, allow_duplicate_keys=True)
        if error:
            return [self.violation(f"Invalid JSON: {error}; ZCode skips this plugin", path)]
        if not isinstance(data, dict):
            return [self.violation("Manifest must be a JSON object; ZCode skips this plugin", path)]
        violations: List[RuleViolation] = []
        name = data.get("name")
        trimmed = name.strip() if isinstance(name, str) else ""
        if not zcode.NAME_RE.match(trimmed):
            violations.append(
                self.violation(
                    f"Invalid plugin name {safe_display(name)!r}: ZCode requires 1-128 characters of "
                    "lowercase letters, digits, '.', '_' or '-', starting with a letter or "
                    "digit; ZCode skips this plugin",
                    path,
                )
            )
        for key in zcode.UNSUPPORTED_COMPONENT_KEYS:
            if key in data:
                violations.append(
                    self.violation(
                        f"'{key}' is not loaded by ZCode; the component is ignored",
                        path,
                        severity=self.scope_severity(Severity.WARNING),
                    )
                )
        plugin_dir = node.plugin_dir
        for field in zcode.PATH_FIELDS:
            for raw in zcode.path_list(data.get(field)):
                if zcode.lexically_escapes(raw):
                    violations.append(
                        self.violation(
                            f"'{field}' path {safe_display(raw)!r} is absolute or leaves the plugin "
                            "directory; ZCode ignores it",
                            path,
                        )
                    )
                elif self._escapes(plugin_dir, raw):
                    # ZCode's containment check is lexical, so it follows the
                    # symlink and loads the target; skillsaw does not, which
                    # would leave an executable hook or server unscanned.
                    executable = field in ("hooks", "mcpServers")
                    violations.append(
                        self.violation(
                            f"'{field}' path {safe_display(raw)!r} is a symlink out of the "
                            "plugin: ZCode loads it, but skillsaw cannot lint it"
                            + (
                                "; its commands escape hooks-dangerous and mcp checks"
                                if executable
                                else ""
                            )
                            + ". Move the file into the plugin",
                            path,
                            severity=None if executable else self.scope_severity(Severity.WARNING),
                        )
                    )
                elif field == "hooks" and not safe_is_file(plugin_dir / raw):
                    violations.append(
                        self.violation(
                            f"'hooks' names {safe_display(raw)!r}, which is not a file; ZCode reports a "
                            "hooks read error and loads nothing from it",
                            path,
                        )
                    )
                elif field == "mcpServers" and not safe_is_file(plugin_dir / raw):
                    # A missing file loads no servers silently; anything else
                    # unreadable is a ``plugin_mcp_read_failed`` error
                    # (``adapters/src/plugins/mcp.ts:99-119`` in ``zai-org/ZCode``).
                    missing = not safe_exists(plugin_dir / raw)
                    violations.append(
                        self.violation(
                            f"'mcpServers' names {safe_display(raw)!r}, which "
                            + (
                                "does not exist; ZCode loads no servers from it"
                                if missing
                                else "is not a file; ZCode reports an MCP read error"
                            ),
                            path,
                            severity=self.scope_severity(Severity.WARNING) if missing else None,
                        )
                    )
                elif field == "skills" and not safe_exists(plugin_dir / raw):
                    violations.append(
                        self.violation(
                            f"'skills' names {safe_display(raw)!r}, which does not exist",
                            path,
                            severity=self.scope_severity(Severity.WARNING),
                        )
                    )
        for conventional in ("/".join(zcode.CONVENTIONAL_HOOKS), zcode.CONVENTIONAL_MCP):
            if self._escapes(plugin_dir, conventional):
                violations.append(
                    self.violation(
                        f"{conventional} is a symlink out of the plugin: ZCode loads it, but "
                        "skillsaw cannot lint it, so its commands escape hooks-dangerous and "
                        "mcp checks. Move the file into the plugin",
                        path,
                    )
                )
        commands = data.get("commands")
        if isinstance(commands, dict):
            violations.extend(self._check_command_map(node, commands))
        return violations

    def _check_command_map(
        self, node: ZCodePluginConfigNode, commands: Dict[str, Any]
    ) -> List[RuleViolation]:
        """Object-form ``commands``: ``{name: {source | content, ...}}``.

        ZCode writes each entry out as a Markdown command, and skips an
        entry whose name does not normalize to a command name or that does
        not give exactly one of ``source`` and ``content``
        (``adapters/src/plugins/index.ts:716-811`` in ``zai-org/ZCode``).
        """
        violations: List[RuleViolation] = []
        for raw_name, entry in commands.items():
            label = f"Command {safe_display(raw_name)!r}"
            normalized = raw_name.strip().lstrip("/").lower()
            if not zcode.COMMAND_NAME_RE.match(normalized):
                violations.append(
                    self.violation(
                        f"{label}: name must be lowercase letters, digits, '_', ':' or '-' "
                        "(up to 64); ZCode skips it",
                        node.path,
                    )
                )
                continue
            if not isinstance(entry, dict):
                violations.append(
                    self.violation(f"{label} must be an object; ZCode skips it", node.path)
                )
                continue
            source = entry.get("source") if isinstance(entry.get("source"), str) else None
            content = entry.get("content") if isinstance(entry.get("content"), str) else None
            if bool(source) == bool(content):
                violations.append(
                    self.violation(
                        f"{label} must set exactly one of 'source' and 'content'; ZCode skips it",
                        node.path,
                    )
                )
                continue
            if source:
                relative = source[2:] if source.startswith("./") else source
                if zcode.lexically_escapes(relative):
                    violations.append(
                        self.violation(
                            f"{label}: 'source' {safe_display(source)!r} leaves the plugin directory; "
                            "ZCode skips it",
                            node.path,
                        )
                    )
                elif not safe_is_file(node.plugin_dir / relative):
                    violations.append(
                        self.violation(
                            f"{label}: 'source' {safe_display(source)!r} does not exist; ZCode skips it",
                            node.path,
                        )
                    )
                elif self._escapes(node.plugin_dir, relative):
                    violations.append(
                        self.violation(
                            f"{label}: 'source' {safe_display(source)!r} is a symlink out of the "
                            "plugin: ZCode loads it, but skillsaw cannot lint it. Move the file "
                            "into the plugin",
                            node.path,
                            severity=self.scope_severity(Severity.WARNING),
                        )
                    )
        return violations

    @staticmethod
    def _escapes(plugin_dir, relative: str) -> bool:
        """Whether an existing in-plugin path resolves outside the plugin.

        ZCode's containment check is lexical, so it follows such a symlink
        and loads the target; skillsaw does not, so the content goes unlinted.
        """
        root = safe_resolve(plugin_dir)
        candidate = plugin_dir / relative
        return (
            root is not None
            and safe_exists(candidate)
            and contained_resolve(candidate, root) is None
        )

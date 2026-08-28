"""
Rule: opencode-config-valid
"""

from pathlib import Path
from typing import Any, Dict, List, Mapping, Tuple

from skillsaw.blocks import OpenCodeConfigBlock, OpenCodeMcpBlock
from skillsaw.context import HAS_OPENCODE, RepositoryContext
from skillsaw.diagnostics import safe_display
from skillsaw.formats import opencode as oc
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.rules.builtin.secret_detection import (
    DEFAULT_PLACEHOLDER_MARKERS,
    mapped_secret_description,
    url_has_userinfo,
)

#: The one v1 server form that carries no ``type``: a bare ``{"enabled":
#: bool}`` toggling a server inherited from a remote organization config.
#: v2 ignores it, but v1 reads it, so it is not a missing ``type``.
_TOGGLE_ONLY_KEYS = frozenset({"enabled", "disabled"})


class OpenCodeConfigValidRule(Rule):
    """Check that opencode.json(c) is parseable and shaped the way OpenCode reads it"""

    since = "0.20.0"

    formats = frozenset({HAS_OPENCODE})

    config_schema = {
        "extra-keys": {
            "type": "list",
            "default": [],
            "description": (
                "Additional top-level config keys to accept, for keys newer "
                "than this skillsaw release"
            ),
        },
        "additional-placeholders": {
            "type": "list",
            "default": [],
            "description": (
                "Extra case-insensitive substrings that mark a generic "
                "credential value as a placeholder (suppressing the violation)"
            ),
        },
    }

    @property
    def rule_id(self) -> str:
        return "opencode-config-valid"

    @property
    def description(self) -> str:
        return "opencode.json(c) must parse and use keys and MCP server shapes OpenCode reads"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        # The same document is attached under two parser roles. The config
        # role drives this rule; the MCP role is looked up per path so the
        # server shape is read through the one accessor the policy rules use,
        # rather than being re-derived here where the two could drift.
        mcp_blocks = {
            block.resolved_path: block for block in context.lint_tree.find(OpenCodeMcpBlock)
        }

        for block in context.lint_tree.find(OpenCodeConfigBlock):
            if block.parse_error:
                # The only error-severity finding: OpenCode cannot read the
                # file at all, so nothing it configures is in effect.
                violations.append(
                    self.violation(
                        f"Invalid JSON: {block.parse_error}",
                        file_path=block.path,
                    )
                )
                continue

            data = block.raw_data
            if data is None:
                violations.append(
                    self.violation(
                        "OpenCode configuration must be a JSON object",
                        file_path=block.path,
                    )
                )
                continue

            violations.extend(self._check_schema(data, block.path))
            violations.extend(self._check_top_level_keys(data, block.path))
            violations.extend(self._mixed_spellings(data, oc.TOP_LEVEL_V1_TO_V2, block.path))
            violations.extend(self._check_agents(data, block.path))
            violations.extend(self._check_commands(data, block.path))
            mcp_block = mcp_blocks.get(block.resolved_path)
            if mcp_block is not None:
                violations.extend(self._check_mcp(data, mcp_block))

        return violations

    # -- top level ---------------------------------------------------------

    def _check_schema(self, data: Dict[str, Any], path: Path) -> List[RuleViolation]:
        """``$schema`` is optional; when present it must name a schema.

        Editors resolve it for completion and inline validation, so a wrong
        value costs the author their editor support without OpenCode itself
        complaining.
        """
        if "$schema" not in data:
            return []
        value = data["$schema"]
        if not isinstance(value, str) or not value.strip():
            return [
                self.violation(
                    "'$schema' must be a URL string",
                    file_path=path,
                    severity=Severity.WARNING,
                )
            ]
        if value == oc.SCHEMA_URL:
            return []
        if value == oc.TUI_SCHEMA_URL:
            return [
                self.violation(
                    f"'$schema' names the TUI schema ({oc.TUI_SCHEMA_URL}), which "
                    f"describes tui.json — use {oc.SCHEMA_URL} here",
                    file_path=path,
                    severity=Severity.WARNING,
                )
            ]
        # A vendored or mirrored copy is legitimate, so this is information
        # rather than a defect.
        return [
            self.violation(
                f"'$schema' is {safe_display(value)}; OpenCode documents {oc.SCHEMA_URL}",
                file_path=path,
                severity=Severity.INFO,
            )
        ]

    def _known_top_level_keys(self) -> frozenset:
        """Documented keys plus any the project declares.

        The declared type is not enforced when the config loads, so a value
        of the wrong shape simply contributes no extra keys rather than
        raising and costing the whole rule its findings.
        """
        extra = self.setting("extra-keys")
        if not isinstance(extra, (list, tuple, set, frozenset)):
            return oc.TOP_LEVEL_KEYS
        return oc.TOP_LEVEL_KEYS | {key for key in extra if isinstance(key, str)}

    def _check_top_level_keys(self, data: Dict[str, Any], path: Path) -> List[RuleViolation]:
        """Report keys OpenCode does not read.

        Information, never an error. OpenCode's schema moves quickly, and a
        key this release has not heard of is more likely new than wrong —
        so the message names ``extra-keys``, which gives a same-day remedy.
        """
        unknown = oc.unknown_keys(data, self._known_top_level_keys())
        if not unknown:
            return []
        named = ", ".join(f"'{safe_display(key)}'" for key in unknown)
        plural = len(unknown) > 1
        return [
            self.violation(
                f"Unrecognized top-level {'keys' if plural else 'key'} {named} — OpenCode "
                f"reads neither the 1.x nor the 2.0 spelling of "
                f"{'these names' if plural else 'this name'}, so "
                f"{'they configure' if plural else 'it configures'} nothing. If "
                f"{'they were' if plural else 'it was'} added after this skillsaw "
                "release, list it under opencode-config-valid 'extra-keys'.",
                file_path=path,
                severity=Severity.INFO,
            )
        ]

    def _mixed_spellings(
        self,
        data: Mapping[str, Any],
        aliases: Mapping[str, str],
        path: Path,
        where: str = "",
    ) -> List[RuleViolation]:
        """Both spellings of one setting, in one document.

        OpenCode 2.0 normalizes the 1.x key into the 2.0 one, so a file that
        declares both hands the same setting to the loader twice and the
        winner depends on merge order. Either key alone is valid; carrying
        both is the finding.

        Driven entirely by the alias tables in
        :mod:`skillsaw.formats.opencode`, so a rename added there is checked
        here without a visit.
        """
        subject = where or "The configuration"
        violations: List[RuleViolation] = []
        for v1_key in sorted(oc.both_spellings(data, aliases)):
            v2_key = aliases[v1_key]
            note = oc.INVERTED_SENSE_NOTE.get(v1_key, "")
            violations.append(
                self.violation(
                    f"{subject} declares both '{v1_key}' and '{v2_key}' — OpenCode 2.0 "
                    f"reads '{v1_key}' as '{v2_key}'{note}, so one of them silently "
                    "wins; keep one",
                    file_path=path,
                    severity=Severity.WARNING,
                )
            )
        return violations

    # -- agents and commands ----------------------------------------------

    @staticmethod
    def _entries(data: Mapping[str, Any], keys: Tuple[str, ...]) -> List[Tuple[str, str, Any]]:
        """``(config key, entry name, entry)`` for every mapping under *keys*."""
        found: List[Tuple[str, str, Any]] = []
        for key in keys:
            section = data.get(key)
            if not isinstance(section, dict):
                continue
            for name, entry in section.items():
                if isinstance(name, str):
                    found.append((key, name, entry))
        return found

    def _check_section_shape(
        self, data: Dict[str, Any], keys: Tuple[str, ...], path: Path
    ) -> List[RuleViolation]:
        """Each of *keys*, when present, must map names to objects."""
        violations: List[RuleViolation] = []
        for key in keys:
            if key in data and not isinstance(data[key], dict):
                violations.append(
                    self.violation(
                        f"'{key}' must be a JSON object mapping names to definitions",
                        file_path=path,
                        severity=Severity.WARNING,
                    )
                )
        return violations

    def _check_agents(self, data: Dict[str, Any], path: Path) -> List[RuleViolation]:
        """Agent entries, in either the 1.x or the 2.0 vocabulary.

        Unknown keys are deliberately not reported: OpenCode folds an
        unrecognized agent field into the provider ``options``, so naming
        one is a supported way to pass a provider-specific setting.
        """
        keys = ("agent", "agents")
        violations = self._check_section_shape(data, keys, path)
        for section, name, entry in self._entries(data, keys):
            where = f"{section}.{safe_display(name)}"
            if not isinstance(entry, dict):
                violations.append(
                    self.violation(
                        f"'{where}' must be an object",
                        file_path=path,
                        severity=Severity.WARNING,
                    )
                )
                continue
            violations.extend(self._check_agent_entry(where, entry, path))
        return violations

    def _check_agent_entry(
        self, where: str, entry: Dict[str, Any], path: Path
    ) -> List[RuleViolation]:
        """One agent definition. Either spelling of every renamed field passes.

        ``prompt``/``system`` and ``disable``/``disabled`` are the pairs the
        1.x-to-2.0 rename created; both halves are accepted and only the
        types are checked.
        """
        violations = self._mixed_spellings(entry, oc.AGENT_V1_TO_V2, path, where=where)
        for key in ("prompt", "system", "description"):
            if key in entry and not isinstance(entry[key], str):
                violations.append(
                    self.violation(
                        f"'{where}.{key}' must be a string",
                        file_path=path,
                        severity=Severity.WARNING,
                    )
                )
        for key in ("disable", "disabled"):
            if key in entry and not isinstance(entry[key], bool):
                violations.append(
                    self.violation(
                        f"'{where}.{key}' must be a boolean",
                        file_path=path,
                        severity=Severity.WARNING,
                    )
                )
        return violations

    def _check_commands(self, data: Dict[str, Any], path: Path) -> List[RuleViolation]:
        """Command entries, in either vocabulary. The key names are unchanged."""
        keys = ("command", "commands")
        violations = self._check_section_shape(data, keys, path)
        for section, name, entry in self._entries(data, keys):
            where = f"{section}.{safe_display(name)}"
            if not isinstance(entry, dict):
                violations.append(
                    self.violation(
                        f"'{where}' must be an object",
                        file_path=path,
                        severity=Severity.WARNING,
                    )
                )
                continue
            template = entry.get("template")
            if "template" in entry and (not isinstance(template, str) or not template.strip()):
                violations.append(
                    self.violation(
                        f"'{where}.template' must be a non-empty string",
                        file_path=path,
                        severity=Severity.WARNING,
                    )
                )
        return violations

    # -- MCP ---------------------------------------------------------------

    def _check_mcp(self, data: Dict[str, Any], block: OpenCodeMcpBlock) -> List[RuleViolation]:
        """The ``mcp`` section, in either the flat 1.x or the nested 2.0 shape."""
        path = block.path
        if "mcp" not in data:
            return []
        if not isinstance(data["mcp"], dict):
            return [
                self.violation(
                    "'mcp' must be a JSON object",
                    file_path=path,
                    severity=Severity.WARNING,
                )
            ]
        servers = block.server_map()
        if servers is None:
            return []
        violations: List[RuleViolation] = []
        for name, server in servers.items():
            shown = safe_display(str(name))
            if not isinstance(server, dict):
                violations.append(
                    self.violation(
                        f"MCP server '{shown}' configuration must be an object",
                        file_path=path,
                        severity=Severity.WARNING,
                    )
                )
                continue
            violations.extend(self._check_mcp_server(shown, server, path))
        return violations

    def _check_mcp_server(
        self, shown: str, server: Dict[str, Any], path: Path
    ) -> List[RuleViolation]:
        """One server entry: transport, connection field, and the maps around it."""
        violations: List[RuleViolation] = []

        unknown = oc.unknown_keys(server, oc.MCP_SERVER_KEYS)
        if unknown:
            named = ", ".join(f"'{safe_display(key)}'" for key in unknown)
            violations.append(
                self.violation(
                    f"MCP server '{shown}' has unrecognized {named}",
                    file_path=path,
                    severity=Severity.INFO,
                )
            )

        violations.extend(
            self._mixed_spellings(
                server, oc.MCP_SERVER_V1_TO_V2, path, where=f"MCP server '{shown}'"
            )
        )
        oauth = server.get("oauth")
        if isinstance(oauth, dict):
            violations.extend(
                self._mixed_spellings(
                    oauth, oc.MCP_OAUTH_V1_TO_V2, path, where=f"MCP server '{shown}' 'oauth'"
                )
            )

        for key in ("enabled", "disabled"):
            if key in server and not isinstance(server[key], bool):
                violations.append(
                    self.violation(
                        f"MCP server '{shown}' '{key}' must be a boolean",
                        file_path=path,
                        severity=Severity.WARNING,
                    )
                )

        if "timeout" in server and not oc.timeout_is_valid(server["timeout"]):
            violations.append(
                self.violation(
                    f"MCP server '{shown}' 'timeout' must be a number of milliseconds "
                    "(1.x) or an object with 'catalog' and 'execution' (2.0)",
                    file_path=path,
                    severity=Severity.WARNING,
                )
            )

        violations.extend(self._check_mcp_maps(shown, server, path))

        server_type = server.get("type")
        if server_type is None:
            # A bare toggle carries no transport by design; anything else
            # that omits ``type`` names no way to reach the server.
            if not (set(server) and set(server) <= _TOGGLE_ONLY_KEYS):
                violations.append(
                    self.violation(
                        f"MCP server '{shown}' is missing 'type' — must be one of: "
                        f"{', '.join(sorted(oc.MCP_SERVER_TYPES))}",
                        file_path=path,
                        severity=Severity.WARNING,
                    )
                )
            return violations

        if server_type not in oc.MCP_SERVER_TYPES:
            violations.append(
                self.violation(
                    f"MCP server '{shown}' has invalid type "
                    f"{safe_display(repr(server_type))} — must be one of: "
                    f"{', '.join(sorted(oc.MCP_SERVER_TYPES))}",
                    file_path=path,
                    severity=Severity.WARNING,
                )
            )
            return violations

        required = oc.MCP_SERVER_TYPES[server_type]
        if required not in server:
            violations.append(
                self.violation(
                    f"MCP server '{shown}' with type '{server_type}' must have a "
                    f"'{required}' field",
                    file_path=path,
                    severity=Severity.WARNING,
                )
            )
        elif required == "command":
            # OpenCode spawns argv directly rather than through a shell, so
            # ``command`` is an array of strings — not the single string
            # every Claude-family host takes.
            value = server["command"]
            if (
                not isinstance(value, list)
                or not value
                or not all(isinstance(part, str) and part.strip() for part in value)
            ):
                violations.append(
                    self.violation(
                        f"MCP server '{shown}' 'command' must be a non-empty array of "
                        'strings, e.g. ["npx", "-y", "pkg"]',
                        file_path=path,
                        severity=Severity.WARNING,
                    )
                )
        elif not isinstance(server["url"], str) or not server["url"].strip():
            violations.append(
                self.violation(
                    f"MCP server '{shown}' 'url' must be a non-empty string",
                    file_path=path,
                    severity=Severity.WARNING,
                )
            )
        elif url_has_userinfo(server["url"]):
            violations.append(
                self.violation(
                    f"MCP server '{shown}' 'url' must not contain user information",
                    file_path=path,
                )
            )
        return violations

    def _check_mcp_maps(
        self, shown: str, server: Dict[str, Any], path: Path
    ) -> List[RuleViolation]:
        """``environment`` and ``headers``: shape, then embedded credentials.

        OpenCode spells the environment map ``environment`` rather than
        ``env``, which is why the shared MCP shape rule cannot scan it — and
        why the scan happens here instead of being lost.
        """
        violations: List[RuleViolation] = []
        for key, header in (("environment", False), ("headers", True)):
            if key not in server:
                continue
            value = server[key]
            if not isinstance(value, dict):
                violations.append(
                    self.violation(
                        f"MCP server '{shown}' '{key}' must be an object",
                        file_path=path,
                        severity=Severity.WARNING,
                    )
                )
                continue
            violations.extend(self._mapped_secret_violations(value, shown, path, header=header))
        return violations

    def _placeholder_markers(self) -> Tuple[str, ...]:
        """The placeholder allowlist, extended by this rule's configuration."""
        extra = self.setting("additional-placeholders")
        if not isinstance(extra, list):
            return DEFAULT_PLACEHOLDER_MARKERS
        return DEFAULT_PLACEHOLDER_MARKERS + tuple(str(m).lower() for m in extra if str(m))

    def _mapped_secret_violations(
        self,
        values: Dict[Any, Any],
        shown: str,
        path: Path,
        *,
        header: bool,
    ) -> List[RuleViolation]:
        """Report structured credentials without copying their values."""
        violations: List[RuleViolation] = []
        markers = self._placeholder_markers()
        location = "HTTP header" if header else "environment variable"
        for name, value in values.items():
            if not isinstance(name, str) or not isinstance(value, str):
                continue
            description = mapped_secret_description(name, value, header=header, markers=markers)
            if description is None:
                continue
            violations.append(
                self.violation(
                    f"MCP server '{shown}' {location} '{safe_display(name)}' embeds "
                    f"{description}; use a placeholder or OpenCode's "
                    "{env:VAR} substitution instead of a credential value",
                    file_path=path,
                )
            )
        return violations

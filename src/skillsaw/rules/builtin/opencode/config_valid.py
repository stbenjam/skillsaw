"""
Rule: opencode-config-valid
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, FrozenSet, Iterator, List, Mapping, Optional, Set, Tuple

from skillsaw.blocks import OpenCodeConfigBlock, OpenCodeMcpBlock
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.diagnostics import safe_display
from skillsaw.formats import opencode as oc
from skillsaw.rule import Rule, RuleViolation, Severity

#: The one v1 server form that carries no ``type``: a bare ``{"enabled":
#: bool}`` toggling a server inherited from a remote organization config.
#: v2 ignores it, but v1 reads it, so it is not a missing ``type``.
_TOGGLE_ONLY_KEYS = frozenset({"enabled", "disabled"})


def _mapping_value_pairs(
    left: Mapping[str, Any], right: Mapping[str, Any]
) -> Iterator[Tuple[Any, Any]]:
    """Yield pairs without retaining work proportional to mapping width."""
    for key in left:
        yield left[key], right[key]


def _json_values_equal(left: Any, right: Any) -> bool:
    """JSON equality matching JavaScript's deep-strict value semantics."""
    comparisons: List[Iterator[Tuple[Any, Any]]] = [iter(((left, right),))]
    while comparisons:
        try:
            left_value, right_value = next(comparisons[-1])
        except StopIteration:
            comparisons.pop()
            continue
        if isinstance(left_value, bool) or isinstance(right_value, bool):
            if not (
                type(left_value) is bool and type(right_value) is bool and left_value is right_value
            ):
                return False
            continue
        if isinstance(left_value, (int, float)) and isinstance(right_value, (int, float)):
            if left_value != right_value:
                return False
            continue
        if type(left_value) is not type(right_value):
            return False
        if isinstance(left_value, dict):
            if left_value.keys() != right_value.keys():
                return False
            comparisons.append(_mapping_value_pairs(left_value, right_value))
            continue
        if isinstance(left_value, list):
            if len(left_value) != len(right_value):
                return False
            comparisons.append(iter(zip(left_value, right_value)))
            continue
        if left_value != right_value:
            return False
    return True


def _lower_string_model_selection(value: str) -> Dict[str, str] | None:
    """Lower a provider/model string with an optional ``#variant`` suffix."""
    if "/" not in value:
        return None
    provider, selected = value.split("/", 1)
    if not provider or "#" in provider or not selected or selected.count("#") > 1:
        return None
    if "#" not in selected:
        return {"model": value}
    model, variant = selected.split("#", 1)
    if not model or not variant:
        return None
    return {"model": f"{provider}/{model}", "variant": variant}


def _lower_object_model_selection(value: Dict[str, Any]) -> Dict[str, str] | None:
    """Lower a provider/model selection object to OpenCode 1.x fields."""
    provider = value.get("providerID")
    model = value.get("model")
    if (
        not isinstance(provider, str)
        or not provider
        or "/" in provider
        or "#" in provider
        or not isinstance(model, str)
        or not model
        or "#" in model
    ):
        return None
    lowered = {"model": f"{provider}/{model}"}
    if "variant" in value:
        variant = value["variant"]
        if not isinstance(variant, str) or not variant or "#" in variant:
            return None
        lowered["variant"] = variant
    return lowered


def _lower_model_selection(value: Any) -> Dict[str, str] | None:
    """Lower one valid OpenCode 2.0 model selection to its 1.x fields."""
    if isinstance(value, str):
        return _lower_string_model_selection(value)
    if isinstance(value, dict):
        return _lower_object_model_selection(value)
    return None


def _lower_native_command(entry: Any) -> Dict[str, Any] | None:
    """Decode and lower the OpenCode 2.0 command fields used for precedence."""
    if not isinstance(entry, dict):
        return None
    template = entry.get("template")
    if not isinstance(template, str) or not template.strip():
        return None

    lowered: Dict[str, Any] = {"template": template}
    for key in ("description", "agent"):
        if key not in entry:
            continue
        if not isinstance(entry[key], str):
            return None
        lowered[key] = entry[key]
    if "subtask" in entry:
        if not isinstance(entry["subtask"], bool):
            return None
        lowered["subtask"] = entry["subtask"]
    if "model" in entry:
        model = _lower_model_selection(entry["model"])
        if model is None:
            return None
        lowered.update(model)
    return lowered


class OpenCodeConfigValidRule(Rule):
    """Check that an OpenCode project config parses and is shaped the way OpenCode reads it"""

    since = "0.20.0"
    target_dependencies = ("mcp-valid-json",)
    target_dependency_scopes = {"mcp-valid-json": (OpenCodeMcpBlock,)}

    repo_types = frozenset({RepositoryType.OPENCODE})

    config_schema = {
        "extra-keys": {
            "type": "list",
            "default": [],
            "description": (
                "Additional config keys to accept, at the top level or on an "
                "MCP server entry, for keys newer than this skillsaw release"
            ),
        },
    }

    @property
    def rule_id(self) -> str:
        return "opencode-config-valid"

    @property
    def description(self) -> str:
        return (
            "opencode.json and opencode.jsonc must parse and use keys and "
            "MCP server shapes OpenCode reads"
        )

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
                # No further check is meaningful — OpenCode cannot read the
                # file at all — and the report itself belongs to
                # ``mcp-valid-json``: "this is not JSON" is true whatever
                # dialect the document is written in, and that rule is not
                # gated on a ``version:`` this rule's ``since`` postdates.
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
            violations.extend(
                self._conflicting_collection_entries(
                    data, oc.TOP_LEVEL_COLLECTION_MERGES, block.path
                )
            )
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

    def _accepted_keys(self, documented: FrozenSet[str]) -> FrozenSet[str]:
        """*documented* plus any key the project declares under ``extra-keys``.

        One reader for both key sets — the top level and an MCP server entry
        — because both fail the same way when OpenCode ships a key faster
        than skillsaw does, and a remedy that covered only one of them would
        leave the other's message naming a setting that does not help.

        The declared type is not enforced when the config loads, so a value
        of the wrong shape simply contributes no extra keys rather than
        raising and costing the whole rule its findings.
        """
        extra = self.setting("extra-keys")
        if not isinstance(extra, (list, tuple, set, frozenset)):
            return documented
        return documented | {key for key in extra if isinstance(key, str)}

    def _check_top_level_keys(self, data: Dict[str, Any], path: Path) -> List[RuleViolation]:
        """Report keys OpenCode does not read.

        Information, never an error. OpenCode's schema moves quickly, and a
        key this release has not heard of is more likely new than wrong —
        so the message names ``extra-keys``, which gives a same-day remedy.
        """
        unknown = oc.unknown_keys(data, self._accepted_keys(oc.TOP_LEVEL_KEYS))
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

        A file declaring both hands the same setting to the loader twice,
        and one copy is then ignored. Which one is not readable off the
        file: it turns on the release doing the reading and on where the
        pair sits — under the v2 ``agents`` section the v2 field wins, and
        an MCP server's ``enabled``/``disabled`` resolves one way under a
        1.x binary and the other under a 2.0 one. So the message names no
        winner. It says only that one of the two values is inert, which
        holds under every reading, and "keep one" is the fix whichever
        value survives.

        Either key alone is valid; carrying both is the finding.

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
                    f"{subject} declares both '{v1_key}' and '{v2_key}' — they are the "
                    f"1.x and 2.0 spellings of one setting{note}, and only one of the "
                    "two values is in effect; keep one",
                    file_path=path,
                    severity=Severity.WARNING,
                )
            )
        return violations

    def _conflicting_collection_entries(
        self,
        data: Mapping[str, Any],
        aliases: Mapping[str, str],
        path: Path,
    ) -> List[RuleViolation]:
        """Report only conflicting names in collection sections OpenCode merges."""
        violations: List[RuleViolation] = []
        for v1_key, v2_key in aliases.items():
            v1_entries = data.get(v1_key)
            v2_entries = data.get(v2_key)
            if not isinstance(v1_entries, dict) or not isinstance(v2_entries, dict):
                continue
            for name in sorted(v1_entries.keys() & v2_entries.keys()):
                v1_entry = v1_entries[name]
                v2_entry = v2_entries[name]
                if v1_key == "command":
                    v2_entry = _lower_native_command(v2_entry)
                    if v2_entry is None:
                        continue
                if _json_values_equal(v1_entry, v2_entry):
                    continue
                shown = safe_display(str(name))
                violations.append(
                    self.violation(
                        f"'{v1_key}.{shown}' and '{v2_key}.{shown}' define the same "
                        f"entry differently — OpenCode merges these sections and "
                        f"keeps '{v1_key}.{shown}' when names overlap; keep one "
                        "definition",
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
                    )
                )
        for key in ("disable", "disabled"):
            if key in entry and not isinstance(entry[key], bool):
                violations.append(
                    self.violation(
                        f"'{where}.{key}' must be a boolean",
                        file_path=path,
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
                    )
                )
                continue
            # ``template`` is the only required key on a command entry
            # (``required: ["template"]`` in the published schema), and it
            # is the prompt the command runs. A JSON entry has no body to
            # supply it the way a ``.opencode/commands/*.md`` file does, and
            # OpenCode refuses to load a project configuration that omits it.
            template = entry.get("template")
            if not isinstance(template, str) or not template.strip():
                violations.append(
                    self.violation(
                        f"'{where}.template' must be a non-empty string — it is the "
                        "prompt the command runs, and OpenCode refuses to load a "
                        "configuration whose command has none",
                        file_path=path,
                    )
                )
            if section == "commands":
                for key in ("description", "agent"):
                    if key in entry and not isinstance(entry[key], str):
                        violations.append(
                            self.violation(
                                f"'{where}.{key}' must be a string",
                                file_path=path,
                            )
                        )
                if "subtask" in entry and not isinstance(entry["subtask"], bool):
                    violations.append(
                        self.violation(
                            f"'{where}.subtask' must be a boolean",
                            file_path=path,
                        )
                    )
                if "model" in entry and _lower_model_selection(entry["model"]) is None:
                    violations.append(
                        self.violation(
                            f"'{where}.model' must be a provider/model string or a "
                            "model selection object",
                            file_path=path,
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
                )
            ]
        violations: List[RuleViolation] = []
        entries = block.server_entries()
        seen: Set[str] = set()
        for name, server in entries:
            shown = safe_display(str(name))
            if name in seen:
                # The 1.x and 2.0 layouts both declare this server, so the
                # file ships two objects under one name and only one of them
                # is in effect. The message names no winner: "keep one" is
                # the fix whichever survives, and naming the wrong half would
                # point the author at deleting the live server.
                violations.append(
                    self.violation(
                        f"MCP server '{shown}' is declared under both 'mcp.servers' "
                        "(2.0) and 'mcp' directly (1.x) — they are two separate "
                        "objects and only one of them is in effect; keep one",
                        file_path=path,
                        severity=Severity.WARNING,
                    )
                )
            seen.add(name)
            if not isinstance(server, dict):
                violations.append(
                    self.violation(
                        f"MCP server '{shown}' configuration must be an object",
                        file_path=path,
                    )
                )
                continue
            violations.extend(self._check_mcp_server(shown, server, path))
        return violations

    def _check_mcp_server(
        self, shown: str, server: Dict[str, Any], path: Path
    ) -> List[RuleViolation]:
        """One server entry: transport, connection field, and the maps around it.

        A shape OpenCode's loader rejects makes it refuse to start, so those
        findings take the rule's severity. The one tolerated case is a server
        carrying a boolean ``enabled``: the 1.x ``mcp`` union has a bare
        ``{enabled: boolean}`` toggle branch that ignores excess properties,
        so a broken server with ``enabled`` loads silently as a toggle and
        simply never starts — a warning, not a startup failure.
        """
        violations: List[RuleViolation] = []
        tolerated = isinstance(server.get("enabled"), bool)
        shape_severity = Severity.WARNING if tolerated else None

        unknown = oc.unknown_keys(server, self._accepted_keys(oc.MCP_SERVER_KEYS))
        if unknown:
            named = ", ".join(f"'{safe_display(key)}'" for key in unknown)
            violations.append(
                self.violation(
                    f"MCP server '{shown}' has unrecognized {named} — OpenCode "
                    "loads no such setting. If it was added after this skillsaw "
                    "release, list it under opencode-config-valid 'extra-keys'.",
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
                        severity=shape_severity,
                    )
                )

        if "timeout" in server and not oc.timeout_is_valid(server["timeout"]):
            violations.append(
                self.violation(
                    f"MCP server '{shown}' 'timeout' must be a number of milliseconds "
                    "(1.x) or an object of "
                    f"{'/'.join(sorted(oc.MCP_TIMEOUT_KEYS))} (2.0)",
                    file_path=path,
                    severity=shape_severity,
                )
            )

        violations.extend(self._check_mcp_maps(shown, server, path, shape_severity))

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
                        severity=shape_severity,
                    )
                )
            return violations

        # ``isinstance`` first, and not merely for tidiness:
        # ``MCP_SERVER_TYPES`` is a mapping, so ``not in`` hashes the key, and
        # a list- or dict-valued ``type`` from a hand-edited config would
        # raise ``TypeError`` out of ``check()``. The per-rule guard would
        # catch it, but the whole rule's findings for the repository are
        # replaced by that one crash — so a single typo would cost every
        # other shape and spelling finding in the file.
        if not isinstance(server_type, str) or server_type not in oc.MCP_SERVER_TYPES:
            violations.append(
                self.violation(
                    f"MCP server '{shown}' has invalid type "
                    f"{safe_display(repr(server_type))} — must be one of: "
                    f"{', '.join(sorted(oc.MCP_SERVER_TYPES))}",
                    file_path=path,
                    severity=shape_severity,
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
                    severity=shape_severity,
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
                        severity=shape_severity,
                    )
                )
        elif not isinstance(server["url"], str) or not server["url"].strip():
            violations.append(
                self.violation(
                    f"MCP server '{shown}' 'url' must be a non-empty string",
                    file_path=path,
                    severity=shape_severity,
                )
            )
        # A credential-bearing ``url`` is deliberately *not* checked here.
        # ``url`` means the same thing in every dialect, so ``mcp-valid-json``
        # keeps that one check even for the blocks it defers to this rule —
        # and it is ungated by ``since``, so it still fires for a project
        # pinned to a ``version:`` older than this rule.
        return violations

    def _check_mcp_maps(
        self,
        shown: str,
        server: Dict[str, Any],
        path: Path,
        severity: Optional[Severity] = None,
    ) -> List[RuleViolation]:
        """Shape only, for ``environment``, ``headers`` and ``oauth``.

        The *credentials* in these maps are deliberately not scanned here.
        ``mcp-valid-json`` keeps that scan for the blocks whose shape it
        defers to this rule, reading the map names off
        :attr:`McpBlock.credential_maps` — which is what makes it survive a
        ``.skillsaw.yaml`` pinning a ``version:`` older than this rule's
        ``since``, the ordinary state right after an upgrade. Doing it in
        both places would report one committed token twice.
        """
        violations: List[RuleViolation] = []
        for key in ("environment", "headers", "oauth"):
            if key not in server:
                continue
            value = server[key]
            if isinstance(value, dict):
                continue
            # ``oauth: false`` is the documented way to switch OAuth off, so
            # only a non-dict that is not that is a shape defect.
            if key == "oauth" and value is False:
                continue
            violations.append(
                self.violation(
                    f"MCP server '{shown}' '{key}' must be an object",
                    file_path=path,
                    severity=severity,
                )
            )
        return violations

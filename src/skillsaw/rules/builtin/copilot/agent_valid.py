"""Validate GitHub Copilot and VS Code custom-agent frontmatter."""

from __future__ import annotations

import re
from typing import Any, List, Optional, Tuple

from skillsaw.context import HAS_COPILOT, RepositoryContext
from skillsaw.diagnostics import safe_display
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.rules.builtin.content_analysis import CopilotAgentBlock
from skillsaw.rules.builtin.hooks.json_valid import (
    _OPTIONAL_FIELD_TYPES,
    _TYPE_REQUIRED_FIELDS,
    _TYPE_SPECIFIC_FIELDS,
    _VALID_HOOK_EVENTS,
    _VALID_HOOK_TYPES,
    _check_field_type,
    _format_type_name,
)
from skillsaw.rules.builtin.utils import (
    commented_item_line,
    commented_key_line,
    read_frontmatter_commented,
)

_TARGETS = frozenset({"vscode", "github-copilot"})
_KNOWN_FIELDS = frozenset(
    {
        "name",
        "description",
        "argument-hint",
        "target",
        "tools",
        "model",
        "agents",
        "user-invocable",
        "disable-model-invocation",
        "infer",
        "mcp-servers",
        "metadata",
        "handoffs",
        "hooks",
    }
)
_AGENT_TOOL_ALIASES = frozenset({"agent", "custom-agent", "task"})
_QUALIFIED_MODEL = re.compile(r"^\S(?:.*\S)?\s+\([^)]+\)$")


def _fm_line(line: Optional[int]) -> Optional[int]:
    """Translate a frontmatter-relative ruamel line to a file line."""
    return line + 1 if line is not None else None


def _key_line(node: Any, key: str) -> Optional[int]:
    return _fm_line(commented_key_line(node, key))


def _item_line(node: Any, index: int) -> Optional[int]:
    return _fm_line(commented_item_line(node, index))


def _type_name(value: Any) -> str:
    if isinstance(value, str):
        return "string"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        return "mapping"
    if isinstance(value, list):
        return "list"
    if value is None:
        return "null"
    return type(value).__name__


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


class CopilotAgentValidRule(Rule):
    """Validate target-aware custom-agent YAML and cross-field semantics."""

    since = "0.20.0"
    formats = frozenset({HAS_COPILOT})
    target_dependencies = ("content-description-routing",)

    config_schema = {
        "report-unknown-fields": {
            "type": "bool",
            "default": False,
            "description": (
                "Warn about unknown top-level custom-agent fields; disabled by default "
                "because the format evolves quickly"
            ),
        }
    }

    @property
    def rule_id(self) -> str:
        return "copilot-agent-valid"

    @property
    def description(self) -> str:
        return "Copilot and VS Code custom agents must use target-compatible frontmatter"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        for block in context.lint_tree.find(CopilotAgentBlock):
            violations.extend(self._check_agent(block))
        return violations

    def _finding(
        self,
        block: CopilotAgentBlock,
        message: str,
        *,
        line: Optional[int] = None,
        severity: Optional[Severity] = None,
        discriminator: Optional[str] = None,
    ) -> RuleViolation:
        return self.violation(
            message,
            file_path=block.path,
            line=line,
            block=block,
            severity=severity,
            fixable=False,
            fingerprint_discriminator=discriminator,
        )

    def _check_agent(self, block: CopilotAgentBlock) -> List[RuleViolation]:
        if block.frontmatter_error:
            return [
                self._finding(
                    block,
                    block.frontmatter_error,
                    line=block.frontmatter_error_line,
                    discriminator="frontmatter",
                )
            ]
        # Description routing remains the owner of a completely missing
        # frontmatter block (and therefore of the missing description).
        if not block.has_frontmatter:
            return []

        data, error, error_line = read_frontmatter_commented(block.path)
        if error:
            return [
                self._finding(
                    block,
                    f"Invalid frontmatter: {error}",
                    line=error_line,
                    discriminator="frontmatter",
                )
            ]
        if not isinstance(data, dict):
            return [
                self._finding(
                    block,
                    "Custom-agent frontmatter must be a YAML mapping",
                    discriminator="frontmatter",
                )
            ]

        violations: List[RuleViolation] = []
        target = self._check_target(block, data, violations)
        if not block.path.name.endswith(".agent.md"):
            target = "vscode"
        self._check_scalar(block, data, "name", violations)
        self._check_description(block, data, violations)
        argument_hint_valid = self._check_scalar(block, data, "argument-hint", violations)

        for key in ("user-invocable", "disable-model-invocation", "infer"):
            self._check_boolean(block, data, key, violations)
        if "infer" in data:
            suffix = (
                "; 'disable-model-invocation' is also set and takes precedence"
                if "disable-model-invocation" in data
                else ""
            )
            violations.append(
                self._finding(
                    block,
                    "'infer' is retired; use 'disable-model-invocation' and "
                    f"'user-invocable' instead{suffix}",
                    line=_key_line(data, "infer"),
                    severity=Severity.WARNING,
                    discriminator="infer:retired",
                )
            )

        tools_valid, tool_names, tools_is_string = self._check_tools(block, data, violations)
        model_valid, model_is_list = self._check_model(block, data, violations)
        agents_valid, agent_names = self._check_agents(block, data, violations)
        metadata_valid = self._check_metadata(block, data, violations)
        handoffs_valid = self._check_handoffs(block, data, violations)
        mcp_valid = self._check_mapping_field(block, data, "mcp-servers", violations)
        hooks_valid = self._check_hooks(block, data, violations)

        supports_agents = target != "github-copilot"
        if supports_agents and agents_valid and agent_names and "tools" in data and tools_valid:
            restricted = "*" not in tool_names
            if restricted and not (_AGENT_TOOL_ALIASES & {name.casefold() for name in tool_names}):
                violations.append(
                    self._finding(
                        block,
                        "A non-empty 'agents' list requires the 'agent' tool (or a compatible "
                        "'custom-agent'/'Task' alias) when 'tools' is restricted",
                        line=_key_line(data, "agents"),
                        discriminator="agents:tool",
                    )
                )

        self._check_target_compatibility(
            block,
            data,
            target,
            violations,
            argument_hint_valid=argument_hint_valid,
            agents_valid=agents_valid,
            handoffs_valid=handoffs_valid,
            hooks_valid=hooks_valid,
            metadata_valid=metadata_valid,
            mcp_valid=mcp_valid,
            model_valid=model_valid,
            model_is_list=model_is_list,
            tools_valid=tools_valid,
            tools_is_string=tools_is_string,
        )

        includes_cloud = target != "vscode"
        if includes_cloud and len(block.body_text) > 30_000:
            violations.append(
                self._finding(
                    block,
                    f"Agent prompt is {len(block.body_text):,} characters; the GitHub Copilot "
                    "cloud limit is 30,000",
                    discriminator="body:length",
                )
            )

        if self.setting("report-unknown-fields") is True:
            for key in data:
                if key in _KNOWN_FIELDS:
                    continue
                violations.append(
                    self._finding(
                        block,
                        f"Unknown custom-agent field '{safe_display(key)}'",
                        line=_key_line(data, key) if isinstance(key, str) else None,
                        severity=Severity.WARNING,
                        discriminator=f"unknown:{safe_display(key)}",
                    )
                )

        return violations

    def _check_target(
        self, block: CopilotAgentBlock, data: dict, violations: List[RuleViolation]
    ) -> Optional[str]:
        if "target" not in data:
            return None
        target = data["target"]
        line = _key_line(data, "target")
        if not isinstance(target, str):
            violations.append(
                self._finding(
                    block,
                    f"'target' must be 'vscode' or 'github-copilot', got {_type_name(target)}",
                    line=line,
                    discriminator="target:type",
                )
            )
            return None
        if target not in _TARGETS:
            violations.append(
                self._finding(
                    block,
                    f"Invalid target '{safe_display(target)}'; expected 'vscode' or "
                    "'github-copilot'",
                    line=line,
                    discriminator="target:value",
                )
            )
            return None
        return target

    def _check_scalar(
        self, block: CopilotAgentBlock, data: dict, key: str, violations: List[RuleViolation]
    ) -> bool:
        if key not in data:
            return False
        if not _nonempty_string(data[key]):
            violations.append(
                self._finding(
                    block,
                    f"'{key}' must be a non-empty string, got {_type_name(data[key])}",
                    line=_key_line(data, key),
                    discriminator=f"{key}:type",
                )
            )
            return False
        return True

    def _check_description(
        self, block: CopilotAgentBlock, data: dict, violations: List[RuleViolation]
    ) -> None:
        if "description" not in data:
            return
        value = data["description"]
        # Empty descriptions are content-quality findings owned by
        # content-description-routing. Only a non-string is a schema defect.
        if not isinstance(value, str):
            violations.append(
                self._finding(
                    block,
                    f"'description' must be a string, got {_type_name(value)}",
                    line=_key_line(data, "description"),
                    discriminator="description:type",
                )
            )

    def _check_boolean(
        self, block: CopilotAgentBlock, data: dict, key: str, violations: List[RuleViolation]
    ) -> None:
        if key in data and not isinstance(data[key], bool):
            violations.append(
                self._finding(
                    block,
                    f"'{key}' must be a boolean, got {_type_name(data[key])}",
                    line=_key_line(data, key),
                    discriminator=f"{key}:type",
                )
            )

    def _check_string_list(
        self,
        block: CopilotAgentBlock,
        key: str,
        value: Any,
        violations: List[RuleViolation],
        *,
        allow_empty: bool,
    ) -> Tuple[bool, List[str]]:
        if not isinstance(value, list):
            violations.append(
                self._finding(
                    block,
                    f"'{key}' must be a list of strings, got {_type_name(value)}",
                    line=block.key_line(key),
                    discriminator=f"{key}:type",
                )
            )
            return False, []
        if not value and not allow_empty:
            violations.append(
                self._finding(
                    block,
                    f"'{key}' must contain at least one model",
                    line=block.key_line(key),
                    discriminator=f"{key}:empty",
                )
            )
            return False, []
        valid = True
        strings: List[str] = []
        for index, item in enumerate(value):
            if not _nonempty_string(item):
                violations.append(
                    self._finding(
                        block,
                        f"'{key}[{index}]' must be a non-empty string, got " f"{_type_name(item)}",
                        line=_item_line(value, index),
                        discriminator=f"{key}:item:{index}",
                    )
                )
                valid = False
                continue
            strings.append(item.strip())
        return valid, strings

    def _check_tools(
        self, block: CopilotAgentBlock, data: dict, violations: List[RuleViolation]
    ) -> Tuple[bool, List[str], bool]:
        if "tools" not in data:
            return True, [], False
        value = data["tools"]
        if isinstance(value, str):
            parts = [part.strip() for part in value.split(",")]
            if not value.strip() or any(not part for part in parts):
                violations.append(
                    self._finding(
                        block,
                        "'tools' string must contain one or more comma-separated tool names",
                        line=_key_line(data, "tools"),
                        discriminator="tools:value",
                    )
                )
                return False, [], True
            return True, parts, True
        if isinstance(value, list):
            valid, names = self._check_string_list(
                block, "tools", value, violations, allow_empty=True
            )
            return valid, names, False
        violations.append(
            self._finding(
                block,
                f"'tools' must be a string or list of strings, got {_type_name(value)}",
                line=_key_line(data, "tools"),
                discriminator="tools:type",
            )
        )
        return False, [], False

    def _check_model(
        self, block: CopilotAgentBlock, data: dict, violations: List[RuleViolation]
    ) -> Tuple[bool, bool]:
        if "model" not in data:
            return True, False
        value = data["model"]
        if isinstance(value, str):
            if value.strip():
                return True, False
            violations.append(
                self._finding(
                    block,
                    "'model' must be a non-empty string",
                    line=_key_line(data, "model"),
                    discriminator="model:value",
                )
            )
            return False, False
        if isinstance(value, list):
            valid, _ = self._check_string_list(block, "model", value, violations, allow_empty=False)
            return valid, True
        violations.append(
            self._finding(
                block,
                f"'model' must be a string or prioritized string list, got " f"{_type_name(value)}",
                line=_key_line(data, "model"),
                discriminator="model:type",
            )
        )
        return False, False

    def _check_agents(
        self, block: CopilotAgentBlock, data: dict, violations: List[RuleViolation]
    ) -> Tuple[bool, List[str]]:
        if "agents" not in data:
            return True, []
        value = data["agents"]
        if value == "*":
            return True, ["*"]
        if isinstance(value, list):
            return self._check_string_list(block, "agents", value, violations, allow_empty=True)
        violations.append(
            self._finding(
                block,
                "'agents' must be '*' or a list of custom-agent names",
                line=_key_line(data, "agents"),
                discriminator="agents:type",
            )
        )
        return False, []

    def _check_metadata(
        self, block: CopilotAgentBlock, data: dict, violations: List[RuleViolation]
    ) -> bool:
        if "metadata" not in data:
            return True
        metadata = data["metadata"]
        if not isinstance(metadata, dict):
            violations.append(
                self._finding(
                    block,
                    f"'metadata' must be a string-to-string mapping, got "
                    f"{_type_name(metadata)}",
                    line=_key_line(data, "metadata"),
                    discriminator="metadata:type",
                )
            )
            return False
        valid = True
        for key, value in metadata.items():
            if not isinstance(key, str) or not isinstance(value, str):
                violations.append(
                    self._finding(
                        block,
                        "Each 'metadata' entry must have a string key and string value",
                        line=_key_line(metadata, key),
                        discriminator=f"metadata:item:{safe_display(key)}",
                    )
                )
                valid = False
        return valid

    def _check_handoffs(
        self, block: CopilotAgentBlock, data: dict, violations: List[RuleViolation]
    ) -> bool:
        if "handoffs" not in data:
            return True
        handoffs = data["handoffs"]
        if not isinstance(handoffs, list):
            violations.append(
                self._finding(
                    block,
                    f"'handoffs' must be a list, got {_type_name(handoffs)}",
                    line=_key_line(data, "handoffs"),
                    discriminator="handoffs:type",
                )
            )
            return False
        valid = True
        for index, handoff in enumerate(handoffs):
            item_line = _item_line(handoffs, index)
            if not isinstance(handoff, dict):
                violations.append(
                    self._finding(
                        block,
                        f"'handoffs[{index}]' must be a mapping",
                        line=item_line,
                        discriminator=f"handoffs:item:{index}",
                    )
                )
                valid = False
                continue
            for key in ("label", "agent"):
                if key not in handoff:
                    violations.append(
                        self._finding(
                            block,
                            f"'handoffs[{index}]' requires a non-empty '{key}' string",
                            line=item_line,
                            discriminator=f"handoffs:{index}:{key}:missing",
                        )
                    )
                    valid = False
                elif not _nonempty_string(handoff[key]):
                    violations.append(
                        self._finding(
                            block,
                            f"'handoffs[{index}].{key}' must be a non-empty string",
                            line=_key_line(handoff, key) or item_line,
                            discriminator=f"handoffs:{index}:{key}:type",
                        )
                    )
                    valid = False
            for key in ("prompt", "model"):
                if key in handoff and not _nonempty_string(handoff[key]):
                    violations.append(
                        self._finding(
                            block,
                            f"'handoffs[{index}].{key}' must be a non-empty string",
                            line=_key_line(handoff, key) or item_line,
                            discriminator=f"handoffs:{index}:{key}:type",
                        )
                    )
                    valid = False
            if (
                "model" in handoff
                and _nonempty_string(handoff["model"])
                and not _QUALIFIED_MODEL.fullmatch(handoff["model"])
            ):
                violations.append(
                    self._finding(
                        block,
                        f"'handoffs[{index}].model' must be qualified as 'Model Name (vendor)'",
                        line=_key_line(handoff, "model") or item_line,
                        discriminator=f"handoffs:{index}:model:qualified",
                    )
                )
                valid = False
            if "send" in handoff and not isinstance(handoff["send"], bool):
                violations.append(
                    self._finding(
                        block,
                        f"'handoffs[{index}].send' must be a boolean",
                        line=_key_line(handoff, "send") or item_line,
                        discriminator=f"handoffs:{index}:send:type",
                    )
                )
                valid = False
        return valid

    def _check_mapping_field(
        self, block: CopilotAgentBlock, data: dict, key: str, violations: List[RuleViolation]
    ) -> bool:
        if key not in data:
            return True
        if isinstance(data[key], dict):
            return True
        violations.append(
            self._finding(
                block,
                f"'{key}' must be a mapping, got {_type_name(data[key])}",
                line=_key_line(data, key),
                discriminator=f"{key}:type",
            )
        )
        return False

    def _check_hooks(
        self, block: CopilotAgentBlock, data: dict, violations: List[RuleViolation]
    ) -> bool:
        if "hooks" not in data:
            return True
        hooks = data["hooks"]
        if not isinstance(hooks, dict):
            violations.append(
                self._finding(
                    block,
                    f"'hooks' must be a mapping, got {_type_name(hooks)}",
                    line=_key_line(data, "hooks"),
                    discriminator="hooks:type",
                )
            )
            return False
        valid = True
        for event, configs in hooks.items():
            event_line = _key_line(hooks, event)
            shown_event = safe_display(event)
            if not isinstance(event, str) or event not in _VALID_HOOK_EVENTS:
                violations.append(
                    self._finding(
                        block,
                        f"Unknown hook event '{shown_event}'",
                        line=event_line,
                        discriminator=f"hooks:event:{shown_event}",
                    )
                )
                valid = False
            if not isinstance(configs, list):
                violations.append(
                    self._finding(
                        block,
                        f"Hook event '{shown_event}' must contain a list of configurations",
                        line=event_line,
                        discriminator=f"hooks:{shown_event}:type",
                    )
                )
                valid = False
                continue
            for index, config in enumerate(configs):
                config_line = _item_line(configs, index) or event_line
                if not isinstance(config, dict):
                    violations.append(
                        self._finding(
                            block,
                            f"Hook event '{shown_event}[{index}]' must be a mapping",
                            line=config_line,
                            discriminator=f"hooks:{shown_event}:{index}:type",
                        )
                    )
                    valid = False
                    continue
                if "matcher" in config and not isinstance(config["matcher"], str):
                    violations.append(
                        self._finding(
                            block,
                            f"Hook event '{shown_event}[{index}].matcher' must be a string",
                            line=_key_line(config, "matcher") or config_line,
                            discriminator=f"hooks:{shown_event}:{index}:matcher",
                        )
                    )
                    valid = False
                if "hooks" in config:
                    flat_config = False
                    handlers = config["hooks"]
                    if not isinstance(handlers, list):
                        violations.append(
                            self._finding(
                                block,
                                f"Hook event '{shown_event}[{index}].hooks' must be a list",
                                line=_key_line(config, "hooks") or config_line,
                                discriminator=f"hooks:{shown_event}:{index}:handlers",
                            )
                        )
                        valid = False
                        continue
                elif "type" in config:
                    flat_config = True
                    handlers = [config]
                else:
                    violations.append(
                        self._finding(
                            block,
                            f"Hook event '{shown_event}[{index}]' must define 'type' or a "
                            "nested 'hooks' list",
                            line=config_line,
                            discriminator=f"hooks:{shown_event}:{index}:shape",
                        )
                    )
                    valid = False
                    continue
                for handler_index, handler in enumerate(handlers):
                    handler_line = (
                        config_line
                        if flat_config
                        else _item_line(handlers, handler_index) or config_line
                    )
                    if not self._check_hook_handler(
                        block,
                        shown_event,
                        index,
                        handler_index,
                        handler,
                        handler_line,
                        violations,
                    ):
                        valid = False
        return valid

    def _check_hook_handler(
        self,
        block: CopilotAgentBlock,
        event: str,
        config_index: int,
        handler_index: int,
        handler: Any,
        line: Optional[int],
        violations: List[RuleViolation],
    ) -> bool:
        path = f"{event}[{config_index}].hooks[{handler_index}]"
        if not isinstance(handler, dict):
            violations.append(
                self._finding(
                    block,
                    f"Hook '{path}' must be a mapping",
                    line=line,
                    discriminator=f"hooks:{path}:type",
                )
            )
            return False
        hook_type = handler.get("type")
        if not isinstance(hook_type, str) or hook_type not in _VALID_HOOK_TYPES:
            # YAML aliases can build an exponentially expanding acyclic list.
            # Rendering a non-string value before truncating it is therefore
            # not work-bounded; its type is the useful schema diagnostic.
            shown_type = (
                safe_display(hook_type) if isinstance(hook_type, str) else _type_name(hook_type)
            )
            violations.append(
                self._finding(
                    block,
                    f"Hook '{path}' has invalid type '{shown_type}'",
                    line=_key_line(handler, "type") or line,
                    discriminator=f"hooks:{path}:handler-type",
                )
            )
            return False

        valid = True
        for key, expected in _TYPE_REQUIRED_FIELDS[hook_type].items():
            if key not in handler:
                violations.append(
                    self._finding(
                        block,
                        f"Hook '{path}' of type '{hook_type}' requires '{key}'",
                        line=line,
                        discriminator=f"hooks:{path}:{key}:missing",
                    )
                )
                valid = False
            elif not _check_field_type(handler[key], expected) or (
                expected is str and not handler[key].strip()
            ):
                violations.append(
                    self._finding(
                        block,
                        f"Hook '{path}' field '{key}' must be a non-empty "
                        f"{_format_type_name(expected)}",
                        line=_key_line(handler, key) or line,
                        discriminator=f"hooks:{path}:{key}:type",
                    )
                )
                valid = False

        for key, expected in _OPTIONAL_FIELD_TYPES.items():
            if key not in handler:
                continue
            if not _check_field_type(handler[key], expected):
                violations.append(
                    self._finding(
                        block,
                        f"Hook '{path}' field '{key}' must be a " f"{_format_type_name(expected)}",
                        line=_key_line(handler, key) or line,
                        discriminator=f"hooks:{path}:{key}:optional-type",
                    )
                )
                valid = False
        if isinstance(handler.get("args"), list):
            for index, arg in enumerate(handler["args"]):
                if not isinstance(arg, str):
                    violations.append(
                        self._finding(
                            block,
                            f"Hook '{path}' field 'args[{index}]' must be a string",
                            line=_item_line(handler["args"], index)
                            or _key_line(handler, "args")
                            or line,
                            discriminator=f"hooks:{path}:args:{index}",
                        )
                    )
                    valid = False
        for key in handler:
            allowed_types = _TYPE_SPECIFIC_FIELDS.get(key)
            if allowed_types is not None and hook_type not in allowed_types:
                violations.append(
                    self._finding(
                        block,
                        f"Hook '{path}' field '{key}' is only valid for types: "
                        f"{', '.join(sorted(allowed_types))}",
                        line=_key_line(handler, key) or line,
                        severity=Severity.WARNING,
                        discriminator=f"hooks:{path}:{key}:compatibility",
                    )
                )
        return valid

    def _compatibility_warning(
        self,
        block: CopilotAgentBlock,
        data: dict,
        key: str,
        consumer: str,
        violations: List[RuleViolation],
    ) -> None:
        violations.append(
            self._finding(
                block,
                f"'{key}' is ignored by {consumer}",
                line=_key_line(data, key),
                severity=Severity.WARNING,
                discriminator=f"compatibility:{key}:{consumer}",
            )
        )

    def _check_target_compatibility(
        self,
        block: CopilotAgentBlock,
        data: dict,
        target: Optional[str],
        violations: List[RuleViolation],
        *,
        argument_hint_valid: bool,
        agents_valid: bool,
        handoffs_valid: bool,
        hooks_valid: bool,
        metadata_valid: bool,
        mcp_valid: bool,
        model_valid: bool,
        model_is_list: bool,
        tools_valid: bool,
        tools_is_string: bool,
    ) -> None:
        if target == "github-copilot":
            for key, valid in (
                ("argument-hint", argument_hint_valid),
                ("agents", agents_valid),
                ("handoffs", handoffs_valid),
                ("hooks", hooks_valid),
            ):
                if key in data and valid:
                    self._compatibility_warning(
                        block, data, key, "GitHub Copilot cloud", violations
                    )
            if "model" in data and model_valid and model_is_list:
                self._compatibility_warning(
                    block, data, "model", "GitHub Copilot cloud", violations
                )
        elif target == "vscode":
            for key, valid in (("mcp-servers", mcp_valid), ("metadata", metadata_valid)):
                if key in data and valid:
                    self._compatibility_warning(block, data, key, "VS Code", violations)
            if "tools" in data and tools_valid and tools_is_string:
                violations.append(
                    self._finding(
                        block,
                        "VS Code expects 'tools' as a YAML list; the comma-separated string "
                        "spelling is for GitHub Copilot cloud compatibility",
                        line=_key_line(data, "tools"),
                        severity=Severity.WARNING,
                        discriminator="compatibility:tools:vscode",
                    )
                )

"""Validate portable hooks at the component, event, and handler boundaries."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Iterator

from skillsaw.blocks import AgentPluginHooksBlock
from skillsaw.context import RepositoryContext
from skillsaw.diagnostics import safe_display
from skillsaw.formats.agent_plugin_commands import command_problem
from skillsaw.formats.agent_plugins import HOOKS_VERSION, load_agent_plugin_schema
from skillsaw.lint_target import AgentPluginConfigNode
from skillsaw.repository_types import PORTABLE_COMPONENT_REPO_TYPES
from skillsaw.rule import Rule, RuleViolation, Severity

from ._helpers import schema_error_summary, stable_key


@lru_cache(maxsize=1)
def _validators():
    from jsonschema import Draft202012Validator

    schema = load_agent_plugin_schema("hooks.schema.json", HOOKS_VERSION)
    document = Draft202012Validator(schema)
    handler = document.evolve(schema=schema["$defs"]["handler"])
    return document, schema["properties"]["hooks"]["properties"].keys(), handler


class AgentPluginHooksValidRule(Rule):
    """Validate the optional hooks component in an Agent Plugins 1.1.0 package."""

    since = "0.23.0"
    default_enabled = False
    repo_types = PORTABLE_COMPONENT_REPO_TYPES

    @property
    def rule_id(self) -> str:
        return "agent-plugin-hooks-valid"

    @property
    def description(self) -> str:
        return "Portable hooks.json must declare supported events and valid command handlers"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> list[RuleViolation]:
        nodes = context.lint_tree.find(AgentPluginConfigNode)
        findings = [
            self.violation(node.hooks_location_error, file_path=node.plugin_dir / "hooks.json")
            for node in nodes
            if node.hooks_location_error
        ]
        # A symlink can share one hooks file between nested plugins. It is
        # attached once, so collect every declaring plugin as an owner.
        owners: dict[Path, list[tuple[Path, Path]]] = {}
        for node in nodes:
            if node.hooks_file is not None and node.plugin_owner is not None:
                owners.setdefault(node.hooks_file, []).append((node.plugin_dir, node.plugin_owner))
        for block in context.lint_tree.find(AgentPluginHooksBlock):
            block_owners = owners.get(context.resolve_path(block.path), [])
            seen = set()
            for location, message in self._problems(block, block_owners):
                if (location, message) in seen:
                    continue
                seen.add((location, message))
                findings.append(
                    self.violation(
                        message, file_path=block.path, fingerprint_discriminator=location
                    )
                )
        return findings

    @staticmethod
    def _problems(
        block: AgentPluginHooksBlock, owners: list[tuple[Path, Path]]
    ) -> Iterator[tuple[str, str]]:
        if block.parse_error:
            yield "json", f"Invalid JSON: {safe_display(block.parse_error)}"
            return
        data = block.raw_data
        if data is None:
            yield "document", "hooks.json must contain a JSON object"
            return
        document, event_names, handler_validator = _validators()
        hooks = data.get("hooks")
        # An invalid handler or event leaves its siblings usable. Validate the
        # envelope separately, then inspect the members at their own scopes.
        envelope = {**data, "hooks": {}} if isinstance(hooks, dict) else data
        problem = schema_error_summary(document.iter_errors(envelope))
        if problem:
            yield "document", f"Invalid portable hooks configuration: {problem}"
            return
        assert isinstance(hooks, dict)
        for event, entries in hooks.items():
            label = safe_display(event)
            location = stable_key(event)
            if event not in event_names:
                yield location, f"Unknown portable hook event '{label}'"
                continue
            if not isinstance(entries, list) or not entries:
                yield location, f"'{label}' must contain a nonempty array of handlers"
                continue
            for index, entry in enumerate(entries):
                problem = schema_error_summary(handler_validator.iter_errors(entry))
                problems = (
                    [problem]
                    if problem
                    else [
                        command_problem(entry["command"], plugin_dir, plugin_root)
                        for plugin_dir, plugin_root in owners
                    ]
                )
                for problem in filter(None, problems):
                    yield f"{location}:{index}", f"Invalid handler '{label}[{index}]': {problem}"

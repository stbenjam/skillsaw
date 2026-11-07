"""
Rule: zcode-agent-valid

Checks the frontmatter ZCode requires of a subagent — a project one in
``.zcode/agents/*.md``, or one a ZCode plugin ships in ``agents/``:
frontmatter must be present, and so must a non-empty ``name`` and
``description``, or ZCode skips the agent. Plugin agents go through the same
parser as project ones (``bootstrap/src/subagents.ts:187-199`` and
``packages/shared/src/subagent-profile-parser.ts:33-58`` in
``zai-org/ZCode``), with no filename fallback for ``name``.
"""

from typing import List

from skillsaw.blocks import AgentBlock, ZCodeAgentBlock
from skillsaw.context import RepositoryContext
from skillsaw.formats.zcode import zcode_agent_line_values
from skillsaw.lint_target import ZCodePluginConfigNode
from skillsaw.paths import safe_resolve
from skillsaw.rule import Rule, RuleViolation, Severity

from ._helpers import ZCODE_PLUGIN_REPO_TYPES, ZCODE_PROJECT_REPO_TYPES

REQUIRED_FIELDS = ("name", "description")

#: ``memory`` values ZCode accepts; any other value is reported and ignored
#: (``subagent-profile-parser.ts:31``).
MEMORY_SCOPES = ("user", "project", "local")


class ZCodeAgentValidRule(Rule):
    """Validate the frontmatter of a ZCode subagent"""

    since = "0.23.0"

    repo_types = ZCODE_PROJECT_REPO_TYPES | ZCODE_PLUGIN_REPO_TYPES

    @property
    def rule_id(self) -> str:
        return "zcode-agent-valid"

    @property
    def description(self) -> str:
        return "ZCode subagents must declare a name and a description in frontmatter"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    @staticmethod
    def _agents(context: RepositoryContext) -> list:
        """Project agents, then the agents every ZCode plugin ships.

        A plugin's agents are found through its ZCode manifest node — the
        ecosystem's own target type — so a Claude-only plugin's agents, which
        Claude reads with a filename fallback for ``name``, are never asked.
        """
        tree = context.lint_tree
        plugins = {
            resolved
            for node in tree.find(ZCodePluginConfigNode)
            if (resolved := safe_resolve(node.plugin_dir)) is not None
        }
        plugin_agents = [
            block
            for block in tree.find(AgentBlock)
            if (owner := block.provenance_dir()) is not None and safe_resolve(owner) in plugins
        ]
        return [*tree.find(ZCodeAgentBlock), *plugin_agents]

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        for block in self._agents(context):
            name = block.path.name
            if not block.has_frontmatter and not block.frontmatter_error:
                violations.append(
                    self.violation(
                        f"Agent {name} has no frontmatter, so ZCode skips it; add 'name' "
                        "and 'description'",
                        block=block,
                    )
                )
                continue
            values = zcode_agent_line_values(block.read_frontmatter_text())
            for key in REQUIRED_FIELDS:
                value, line = values.get(key, (None, None))
                if not value or not value.strip():
                    violations.append(
                        self.violation(
                            f"Agent {name} needs a non-empty '{key}'; ZCode skips the agent "
                            "without one",
                            block=block,
                            line=line + 1 if line is not None else None,
                        )
                    )
            if "memory" in values:
                value, line = values["memory"]
                # The opening --- is file line 1.
                violations.extend(self._memory(name, block, value, line + 1))
        return violations

    def _memory(self, name: str, block, value, line) -> List[RuleViolation]:
        """A ``memory`` value ZCode ignores."""
        if value in MEMORY_SCOPES:
            return []
        return [
            self.violation(
                f"Agent {name} 'memory' must be one of {', '.join(MEMORY_SCOPES)}; "
                "ZCode ignores the value",
                block=block,
                line=line,
                severity=self.scope_severity(Severity.WARNING),
            )
        ]

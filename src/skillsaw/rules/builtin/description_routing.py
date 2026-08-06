"""Description quality checks for model-routed building blocks."""

import re
from pathlib import Path
from typing import List, Set

from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.rules.builtin.content_analysis import AgentBlock, CommandBlock, SkillBlock

_WORD_RE = re.compile(r"[a-z0-9]+")
_FIRST_PERSON_RE = re.compile(r"\bI(?:'m|'ll|'ve|\s+[A-Za-z]+)\b")
_TRIGGER_MARKERS = (
    "when ",
    "use when",
    "use this",
    "when the user",
    "when users",
    "when you need",
    "triggers on",
    "triggered by",
    "if the user",
    "for requests",
    "for tasks",
)
_RESTATEMENT_FILLER = {"a", "an", "the", "command", "agent", "skill"}


class DescriptionRoutingRule(Rule):
    """Check whether descriptions provide useful routing signals."""

    since = "0.18.0"
    repo_types = {
        RepositoryType.AGENTSKILLS,
        RepositoryType.SINGLE_PLUGIN,
        RepositoryType.MARKETPLACE,
        RepositoryType.DOT_CLAUDE,
        RepositoryType.APM,
        RepositoryType.CODEX_PLUGIN,
        RepositoryType.CODEX_MARKETPLACE,
    }

    config_schema = {
        "require-trigger-phrasing": {
            "type": "bool",
            "default": True,
            "description": ("Require skill and agent descriptions to say when they should be used"),
        },
        "flag-first-person": {
            "type": "bool",
            "default": True,
            "description": "Flag first-person voice in descriptions",
        },
        "flag-name-restatement": {
            "type": "bool",
            "default": True,
            "description": "Flag descriptions that only restate the building block name",
        },
    }

    @property
    def rule_id(self) -> str:
        return "description-routing"

    @property
    def description(self) -> str:
        return "Descriptions should tell the model when to route work to a skill, agent, or command"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        for block_type in (SkillBlock, AgentBlock, CommandBlock):
            for block in context.lint_tree.find(block_type):
                if block.frontmatter_error or not block.has_frontmatter:
                    continue
                description = block.field_value("description")
                if not isinstance(description, str) or not description.strip():
                    continue

                text = description.strip()
                line = block.key_line("description")
                if (
                    block_type is not CommandBlock
                    and self.config.get("require-trigger-phrasing", True)
                    and not self._has_trigger_phrase(text)
                ):
                    violations.append(
                        self.violation(
                            "Description does not say when to use this "
                            f"{block.category}; include trigger phrasing such as 'Use when ...'",
                            block=block,
                            line=line,
                        )
                    )

                if self.config.get("flag-first-person", True) and _FIRST_PERSON_RE.search(text):
                    violations.append(
                        self.violation(
                            "Description uses first-person voice; describe the routing signal directly",
                            block=block,
                            line=line,
                        )
                    )

                if self.config.get("flag-name-restatement", True) and self._restates_name(
                    text, self._block_name(block.path, block.field_value("name"))
                ):
                    violations.append(
                        self.violation(
                            "Description only restates the name; explain what the building block does",
                            block=block,
                            line=line,
                        )
                    )
        return violations

    @staticmethod
    def _has_trigger_phrase(description: str) -> bool:
        normalized = " ".join(description.lower().split())
        return any(marker in normalized for marker in _TRIGGER_MARKERS)

    @staticmethod
    def _block_name(path: Path, configured_name: object) -> str:
        if isinstance(configured_name, str) and configured_name.strip():
            return configured_name
        if path.name.lower() == "skill.md":
            return path.parent.name
        return path.stem

    @staticmethod
    def _tokens(value: str) -> Set[str]:
        return {
            token for token in _WORD_RE.findall(value.lower()) if token not in _RESTATEMENT_FILLER
        }

    @classmethod
    def _restates_name(cls, description: str, name: str) -> bool:
        description_tokens = cls._tokens(description)
        name_tokens = cls._tokens(name)
        return bool(description_tokens and name_tokens and description_tokens <= name_tokens)

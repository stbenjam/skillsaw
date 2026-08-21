"""Description quality checks for skills, agents, and commands."""

import re
from pathlib import Path
from typing import List, Set

from skillsaw.context import HAS_COPILOT, RepositoryContext, RepositoryType
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.rules.builtin.content_analysis import (
    AgentBlock,
    CommandBlock,
    CopilotAgentBlock,
    SkillBlock,
)

_WORD_RE = re.compile(r"[a-z0-9]+")
_USE_THIS_TRIGGER_RE = re.compile(
    r"(?:^|[.!?—]\s+)(?:(?:you )?(?:must|should) )?"
    r"(?:use|invoke) this(?: (?:skill|agent))?(?: proactively)? "
    r"(?:when(?:ever)?|if|before|for|to)\b"
)
_PASSIVE_USE_TRIGGER_RE = re.compile(
    r"(?:^|[.!?—]\s+)(?:this (?:skill|agent) )?(?:must|should) be used "
    r"(?:when(?:ever)?|if|before)\b"
)
_FOR_TRIGGER_RE = re.compile(r"(?:^|[.!?—]\s+)for (?:requests|tasks)\b")
_EXPLANATORY_USER_TRIGGER_RE = re.compile(
    r"\b(?:what happens|what to expect) (?:when (?:the user|users)|if the user)\b"
)
_TRIGGER_MARKERS = (
    "use when",
    "use only when",
    "when the user",
    "when users",
    "when you need",
    "triggers on",
    "triggered by",
    "if the user",
)
_RESTATEMENT_FILLER = {"a", "an", "the", "command", "agent", "skill"}


class DescriptionRoutingRule(Rule):
    """Check whether descriptions provide useful routing or purpose signals."""

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
    # A Copilot repository is often none of the above repo types (a bare
    # ``.github/agents/`` tree is ``UNKNOWN``), so ``enabled: auto`` also fires
    # on the Copilot format — a Copilot agent's description is what routes it,
    # exactly the metadata this rule checks on a Claude agent.
    formats = frozenset({HAS_COPILOT})

    config_schema = {
        "require-trigger-phrasing": {
            "type": "bool",
            "default": True,
            "description": ("Require skill and agent descriptions to say when they should be used"),
        },
        "flag-name-restatement": {
            "type": "bool",
            "default": True,
            "description": "Flag descriptions that only restate the name or generic category",
        },
        "check-user-only-skills": {
            "type": "bool",
            "default": False,
            "description": ("Check skills whose frontmatter sets disable-model-invocation to true"),
        },
    }

    @property
    def rule_id(self) -> str:
        """Return the stable identifier used in configuration and output."""
        return "content-description-routing"

    @property
    def description(self) -> str:
        """Summarize the routing-quality checks performed by this rule."""
        return (
            "Skill and agent descriptions should guide routing; command descriptions should "
            "clearly explain their purpose"
        )

    def default_severity(self) -> Severity:
        """Report routing-quality findings as non-blocking warnings."""
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        """Find weak descriptions across discovered skills, agents, and commands."""
        violations: List[RuleViolation] = []
        for block_type in (SkillBlock, AgentBlock, CopilotAgentBlock, CommandBlock):
            for block in context.lint_tree.find(block_type):
                if block.frontmatter_error:
                    continue
                if (
                    block_type is SkillBlock
                    and self.config.get("check-user-only-skills", False) is not True
                    and block.field_value("disable-model-invocation") is True
                ):
                    continue
                if not block.has_frontmatter:
                    violations.append(
                        self.violation(
                            f"Description is missing; add frontmatter describing this "
                            f"{block.category}",
                            block=block,
                            fingerprint_discriminator="missing-description",
                        )
                    )
                    continue
                description_field = block.field("description")
                if description_field is None:
                    violations.append(
                        self.violation(
                            f"Description is missing; explain what this {block.category} does",
                            block=block,
                            fingerprint_discriminator="missing-description",
                        )
                    )
                    continue
                line = block.key_line("description")
                description = description_field.value
                if not isinstance(description, str) or not description.strip():
                    violations.append(
                        self.violation(
                            "Description is empty; explain what the building block does",
                            block=block,
                            line=line,
                            fingerprint_discriminator="empty-description",
                        )
                    )
                    continue

                text = description.strip()
                # Skills and Claude agents are routed by trigger phrasing, so
                # it is required of them. Commands and Copilot agents/chatmodes
                # carry a capability blurb their host surfaces to the user, not
                # a proactive "Use when ..." selector — they still must have a
                # meaningful, non-name-restating description (checked below),
                # but the trigger-phrasing style is not imposed on them.
                if (
                    block_type not in (CommandBlock, CopilotAgentBlock)
                    and self.config.get("require-trigger-phrasing", True)
                    and not self._has_trigger_phrase(text)
                ):
                    violations.append(
                        self.violation(
                            "Description does not say when to use this "
                            f"{block.category}; include trigger phrasing such as 'Use when ...'",
                            block=block,
                            line=line,
                            fingerprint_discriminator="missing-trigger",
                        )
                    )

                if self.config.get("flag-name-restatement", True) and self._restates_name(
                    text, self._block_name(block.path, block.field_value("name"))
                ):
                    violations.append(
                        self.violation(
                            "Description only restates the name or generic category; explain what "
                            "the building block does",
                            block=block,
                            line=line,
                            fingerprint_discriminator="name-restatement",
                        )
                    )
        return violations

    @staticmethod
    def _has_trigger_phrase(description: str) -> bool:
        """Return whether a description contains a recognized usage trigger."""
        normalized = " ".join(description.lower().split())
        # "Explains what happens when users ..." describes subject matter,
        # not when the building block itself should be selected. Keep direct
        # action clauses such as "Reviews PRs when users ask" valid.
        without_explanatory_clauses = _EXPLANATORY_USER_TRIGGER_RE.sub("", normalized)
        return (
            any(marker in without_explanatory_clauses for marker in _TRIGGER_MARKERS)
            or bool(_USE_THIS_TRIGGER_RE.search(without_explanatory_clauses))
            or bool(_PASSIVE_USE_TRIGGER_RE.search(without_explanatory_clauses))
            or bool(_FOR_TRIGGER_RE.search(without_explanatory_clauses))
        )

    @staticmethod
    def _block_name(path: Path, configured_name: object) -> str:
        """Derive the block name from frontmatter or its conventional path."""
        if isinstance(configured_name, str) and configured_name.strip():
            return configured_name
        if path.name.lower() == "skill.md":
            return path.parent.name
        return path.stem

    @staticmethod
    def _tokens(value: str) -> Set[str]:
        """Normalize meaningful name-comparison tokens from prose."""
        return {
            token for token in _WORD_RE.findall(value.lower()) if token not in _RESTATEMENT_FILLER
        }

    @classmethod
    def _restates_name(cls, description: str, name: str) -> bool:
        """Return whether the description adds no meaning beyond name/category words."""
        description_tokens = cls._tokens(description)
        name_tokens = cls._tokens(name)
        return not description_tokens or bool(name_tokens and description_tokens <= name_tokens)

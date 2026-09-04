"""Description quality checks for skills, agents, and commands."""

import re
from pathlib import Path
from typing import List, Set

from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.rules.builtin.content_analysis import (
    AgentBlock,
    CommandBlock,
    CopilotAgentBlock,
    GrokAgentBlock,
    GrokCommandBlock,
    OpenCodeAgentBlock,
    OpenCodeCommandBlock,
    SkillBlock,
)
from skillsaw.blocks import DevinSkillBlock
from skillsaw.rules.builtin.utils import read_frontmatter_commented

_WORD_RE = re.compile(r"[a-z0-9]+")
# A selection clause at the start of a sentence: an optional subject
# ("you", "Claude", "the agent"), an optional modal, a selection verb, and
# the condition that follows it. Real authors write "Use when …", "Load this
# skill whenever …", "Claude should use this skill after …" and "Invoke it
# for …" interchangeably; the rule is advice, so the vocabulary errs wide.
_ACTIVE_USE_TRIGGER_RE = re.compile(
    r"(?:^|[.!?—:]\s+)"
    r"(?:(?:you|claude|the agent|the assistant|an agent|agents) )?"
    r"(?:(?:must|should|can|may) )?"
    r"(?:(?:use|invoke|load|run|call|apply|activate)(?: this(?: (?:skill|agent|rule|command))?| it)?)"
    r"(?: proactively)? "
    r"(?:when(?:ever)?|if|before|after|during|once|for|to)\b"
)
_PASSIVE_USE_TRIGGER_RE = re.compile(
    r"(?:^|[.!?—:]\s+)(?:this (?:skill|agent|rule|command) )?(?:must|should) be "
    r"(?:used|invoked|loaded|applied) (?:when(?:ever)?|if|before|after|during|once|for)\b"
)
_FOR_TRIGGER_RE = re.compile(r"(?:^|[.!?—:]\s+)for (?:requests|tasks)\b")
_EXPLANATORY_USER_TRIGGER_RE = re.compile(
    r"\b(?:what happens|what to expect) (?:when (?:the user|users)|if the user)\b"
)
# Substring markers, matched on the lower-cased, whitespace-collapsed
# description. The labelled forms ("Trigger:", "Triggers —") are how the
# Agent Skills reference content introduces its activation clause.
_TRIGGER_MARKERS = (
    "use when",
    "use only when",
    "use after",
    "use during",
    "use once",
    "use whenever",
    "when the user",
    "when users",
    "when a user",
    "whenever the user",
    "when asked",
    "whenever asked",
    "when you need",
    "triggers on",
    "triggered by",
    "triggered when",
    "trigger when",
    "triggers when",
    "activates when",
    "activate when",
    "activates on",
    "applies when",
    "apply when",
    "applies to",
    "trigger:",
    "triggers:",
    "trigger —",
    "triggers —",
    "trigger -",
    "triggers -",
    "if the user",
    "if asked",
)
_RESTATEMENT_FILLER = {"a", "an", "the", "command", "agent", "skill"}
#: OpenCode directories whose files are primary agents by location alone —
#: ``config/agent.ts`` scans ``.opencode/{mode,modes}/*.md`` and writes
#: ``mode: "primary"`` for each, whatever the frontmatter says. Only those
#: two directories, and only directly under ``.opencode``: the agent globs
#: are *recursive*, so an ordinary subagent can sit at
#: ``.opencode/agents/modes/reviewer.md`` and matching on the parent name
#: alone would exempt it.
_OPENCODE_PRIMARY_DIRS = frozenset({"mode", "modes"})


class DescriptionRoutingRule(Rule):
    """Check whether descriptions provide useful routing or purpose signals."""

    since = "0.18.0"
    surface_dependencies = ("copilot-agent-valid",)
    repo_types = {
        RepositoryType.AGENTSKILLS,
        RepositoryType.SINGLE_PLUGIN,
        RepositoryType.MARKETPLACE,
        RepositoryType.DOT_CLAUDE,
        RepositoryType.APM,
        RepositoryType.CODEX_PLUGIN,
        RepositoryType.CODEX_MARKETPLACE,
        # A Grok plugin's ``commands/`` and ``agents/`` prose attaches
        # through the same shared plugin pass a Codex plugin's does, so a
        # repository detected only as Grok needs the same activation.
        RepositoryType.GROK_PLUGIN,
        RepositoryType.GROK_MARKETPLACE,
        # A Copilot agent's description is what routes it, exactly the
        # metadata this rule checks on a Claude agent, and the same holds for
        # an OpenCode subagent's description. Without these the
        # ``OpenCodeAgentBlock`` traversal below would never run for exactly
        # the repositories it is for.
        RepositoryType.COPILOT,
        RepositoryType.OPENCODE,
        # Grok routes a subagent by its description the same way, and its
        # commands carry the blurb `grok` shows in the picker. Without this
        # the ``GrokAgentBlock`` and ``GrokCommandBlock`` traversals below
        # would never run on a repository configured only through `.grok/`.
        RepositoryType.GROK_PROJECT,
        # An Antigravity plugin's ``agents/`` and ``commands/`` prose and its
        # ``skills/`` attach through the same shared plugin pass a Codex or
        # Grok plugin's do, so a repository detected only as Antigravity
        # needs the same activation — without it the traversals below simply
        # never run there. Activation only: ``AntigravityAgentBlock``, the
        # *workspace* ``<root>/agents/*.md``, is deliberately absent from the
        # traversal list, because that file's frontmatter contract is
        # unmeasured.
        RepositoryType.ANTIGRAVITY,
        RepositoryType.ANTIGRAVITY_PLUGIN,
    }

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

    @staticmethod
    def _is_user_selected_agent(block_type: type, block) -> bool:
        """Whether this agent is picked by a person rather than routed to.

        OpenCode types its agents: a ``mode: primary`` agent is one the user
        cycles to with Tab, so its description is a label in a menu and no
        "Use when ..." selector applies — the same reason Copilot agents are
        exempt above. ``subagent`` and ``all`` *are* selected automatically
        "based on their descriptions", and ``all`` is the default when the
        field is absent, so only the explicit ``primary`` is exempt.

        Location answers too. Files directly under
        :data:`_OPENCODE_PRIMARY_DIRS` are primary whatever their frontmatter
        says, so they carry no ``mode`` field to read and the directory is
        what exempts them — but only where that directory is ``.opencode``'s
        own, which is why the grandparent is checked as well.
        """
        if block_type is not OpenCodeAgentBlock:
            return False
        parent = block.path.parent
        if parent.name in _OPENCODE_PRIMARY_DIRS and parent.parent.name == ".opencode":
            return True
        return block.field_value("mode") == "primary"

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        """Find weak descriptions across discovered skills, agents, and commands."""
        violations: List[RuleViolation] = []
        for block_type in (
            SkillBlock,
            DevinSkillBlock,
            AgentBlock,
            CopilotAgentBlock,
            OpenCodeAgentBlock,
            GrokAgentBlock,
            CommandBlock,
            OpenCodeCommandBlock,
            GrokCommandBlock,
        ):
            for block in self.dependency_scoped_find(context, block_type):
                if block.frontmatter_error:
                    continue
                # Devin's native skill dialect makes frontmatter optional —
                # the name defaults from the directory — so a skill without
                # one has no description to judge, not a missing one.
                if block_type is DevinSkillBlock and not block.has_frontmatter:
                    continue
                if (
                    block_type is SkillBlock
                    and self.setting("check-user-only-skills") is not True
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
                if block_type is CopilotAgentBlock and not isinstance(description, str):
                    # FrontmatteredBlock's compatibility parser follows YAML
                    # 1.1, where `yes` is boolean. Copilot's schema is YAML
                    # 1.2, so use the same line-preserving parser as its
                    # dedicated rule before making content judgments.
                    parsed, error, _error_line = read_frontmatter_commented(block.path)
                    if error is None and isinstance(parsed, dict) and "description" in parsed:
                        description = parsed["description"]
                if not isinstance(description, str):
                    # Copilot's dedicated schema rule owns wrong-typed
                    # descriptions. Treating the same value as an empty
                    # content description here would emit two diagnoses for
                    # one defect. A bare `description:` key is null, which
                    # is not a type defect but an empty description, and
                    # stays here. Other formats have no schema owner and
                    # keep the established routing finding.
                    if (
                        block_type is CopilotAgentBlock
                        and description is not None
                        and self.surface_rule_enabled("copilot-agent-valid")
                    ):
                        continue
                    violations.append(
                        self.violation(
                            "Description is empty; explain what the building block does",
                            block=block,
                            line=line,
                            fingerprint_discriminator="empty-description",
                        )
                    )
                    continue
                if not description.strip():
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
                    block_type
                    not in (
                        CommandBlock,
                        CopilotAgentBlock,
                        OpenCodeCommandBlock,
                        GrokCommandBlock,
                    )
                    and not self._is_user_selected_agent(block_type, block)
                    and self.setting("require-trigger-phrasing")
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

                if self.setting("flag-name-restatement") and self._restates_name(
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
            or bool(_ACTIVE_USE_TRIGGER_RE.search(without_explanatory_clauses))
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

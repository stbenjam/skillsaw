"""Rule-set profiles: named, curated bundles of rule overrides.

A profile is a set of per-rule overrides (``enabled``, ``severity``, and
rule parameters) applied between the builtin defaults and the user's own
``rules:`` section, so precedence is:

    builtin defaults < profile < user ``rules:`` overrides

Selecting one takes a single config line (``profile: claude-5``) instead of
a hand-maintained ``rules:`` block. The ``default`` profile is empty by
definition — it exists so configs can name the current behavior explicitly.

Profiles are versioned with skillsaw itself: every rule a profile names
ships in the same release, so profile-set ``enabled`` decisions bypass the
config ``version`` gate (choosing a profile is an explicit opt-in to its
rule set). Severity-only and parameter-only entries never change whether a
rule runs — activation still follows the rule's own default and the
``version`` gate.

Adding a profile: add a :class:`Profile` to :data:`PROFILES` with a
rationale comment per rule entry. Rule IDs must be canonical (no legacy
aliases) and must not name deprecated rules — ``tests/test_config.py``
(``TestProfileRegistry``) enforces both, plus valid severities and
``enabled`` values, so a bad entry fails fast in CI rather than being
silently ignored at lint time.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List

DEFAULT_PROFILE = "default"


@dataclass(frozen=True)
class Profile:
    """A named bundle of per-rule config overrides."""

    name: str
    description: str
    # rule_id -> overrides merged under the user's ``rules:`` entry for
    # that rule. Same shape as a config file rule entry: ``enabled``,
    # ``severity``, and any rule parameters from its ``config_schema``.
    rules: Dict[str, Dict[str, Any]] = field(default_factory=dict)


# The claude-5 profile encodes Anthropic's Claude 5 context-engineering
# guidance ("The new rules of context engineering for Claude 5 generation
# models", https://claude.com/blog/the-new-rules-of-context-engineering-for-claude-5-generation-models)
# as severity and enablement deltas over the defaults. See issue #444 for
# the rule-by-rule mapping of the post's shifts onto skillsaw's rule set.
_CLAUDE_5 = Profile(
    name="claude-5",
    description=(
        "Tuned to Anthropic's Claude 5 context-engineering guidance: "
        "elevates duplication and context-bloat rules, tightens token "
        "budgets, enables the stop-condition check, and drops "
        "hedging-language pedantry"
    ),
    rules={
        # "Eliminate duplicate instructions" is a named shift in the post;
        # a directive stated twice in one file is the clearest violation
        # of it.
        "content-repeated-directive": {"severity": "error"},
        # The same shift, across files: drifted near-duplicate sections
        # cost budget twice and disagree with each other.
        "content-instruction-drift": {"severity": "warning"},
        # The post says to remove guidance modern models exhibit by
        # default ("be concise", "think step by step"); tautologies are
        # pure context waste under a lean-context posture.
        "content-tautological": {"severity": "warning"},
        # Progressive disclosure: "for long skills, divide it into many
        # files and split them out" — oversized single sections are the
        # in-file version of the problem.
        "content-section-length": {"severity": "warning"},
        # "Keep your CLAUDE.md lightweight": tighten primary instruction
        # files toward the post's bar, and skills toward
        # split-and-reference territory. Other categories keep defaults.
        "context-budget": {
            "limits": {
                "claude-md": {"warn": 3000, "error": 8000},
                "agents-md": {"warn": 3000, "error": 8000},
                "gemini-md": {"warn": 3000, "error": 8000},
                "skill": {"warn": 2000, "error": 5000},
            },
        },
        # Opt-in agent-safety rule the profile turns on: open-ended loops
        # ("keep monitoring...") with no stop condition burn autonomous
        # sessions.
        "content-missing-stop-condition": {"enabled": True},
        # Judgment-delegating prose ("use judgment", "when appropriate")
        # is the style the post recommends over rigid absolutes; flagging
        # hedges fights it.
        "content-weak-language": {"enabled": False},
    },
)


PROFILES: Dict[str, Profile] = {
    DEFAULT_PROFILE: Profile(
        name=DEFAULT_PROFILE,
        description="The builtin defaults, unchanged",
    ),
    _CLAUDE_5.name: _CLAUDE_5,
}


def available_profiles() -> List[str]:
    """Profile names for error messages and docs, default first."""
    return sorted(PROFILES, key=lambda name: (name != DEFAULT_PROFILE, name))

"""Security hidden instructions rule.

HTML comments are stripped from rendered markdown — the view humans review
on GitHub or in an editor preview — but agents read the raw file. A
directive placed inside an HTML comment is therefore an instruction channel
that is invisible to human review: the classic hiding spot for prompt
injection smuggled into a shared skill, command, or CLAUDE.md.
"""

import re
from typing import List, Optional, Tuple

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.content_analysis import gather_all_content_blocks

# Comment-text prefixes (matched against the stripped, lowercased inner
# text) that are exempt from directive matching. These are well-known
# machine-readable comment channels, not hidden instructions:
#
# - skillsaw's own inline suppression directives (see skillsaw.suppression;
#   the grammar is case-insensitive and every directive starts "skillsaw-")
# - linter/formatter/doc-tool control comments (markdownlint-disable,
#   prettier-ignore, mkdocs anchors, vale off, table-of-contents markers, …)
_ALLOWED_PREFIXES: Tuple[str, ...] = (
    "skillsaw-",
    "markdownlint",
    "prettier",
    "eslint",
    "mkdocs",
    "vale ",
    "toc",
    "textlint",
    "spell-checker",
    "cspell",
    "mdformat",
)

# Directive families. All patterns are precompiled at module level and run
# only against HTML-comment inner text extracted from the markdown AST —
# comments are short (typically one line), so per-comment matching is cheap.
# There is no per-line × per-pattern scan over full bodies, so the
# patterns_matching_anywhere prefilter requirement is satisfied by
# construction; the only whole-body work is a single C-speed "<!--"
# substring gate before touching the AST.

# (a) override: an instruction-cancelling verb near a reference to prior
# context, in either order ("ignore all previous instructions",
# "previous rules no longer apply — disregard them").
_OVERRIDE_VERBS = r"(?:ignore|disregard|forget|override)"
_OVERRIDE_TARGETS = r"(?:previous|prior|above|earlier|instructions|rules|context)"
_OVERRIDE_RE = re.compile(
    rf"\b{_OVERRIDE_VERBS}\b.{{0,40}}?\b{_OVERRIDE_TARGETS}\b"
    rf"|\b{_OVERRIDE_TARGETS}\b.{{0,40}}?\b{_OVERRIDE_VERBS}\b",
    re.IGNORECASE | re.DOTALL,
)

# (b) concealment: telling the agent to hide an action from the user.
_CONCEALMENT_RE = re.compile(
    r"\b(?:do not|don['’]?t|never|avoid)\s+"
    r"(?:tell|inform|mention|reveal|show|alert|notify)\b"
    r"|\bwithout\s+(?:telling|informing|notifying|asking)\b",
    re.IGNORECASE,
)

# (c) execution: naming a download/eval tool outright, or an action verb
# followed by a non-trivial argument token. "Non-trivial" means the token
# immediately after the verb looks like a command, path, URL, or flag
# (contains a backtick, slash, tilde, dollar, or backslash, contains an
# *internal* dot — one followed by a word character, as in payload.sh or
# .env — or starts with a dash) rather than a plain English word — so
# "run `rm -rf ~/.x`" fires while authoring prose like "remove this
# paragraph" or sentence-final punctuation ("ask before you delete
# anything.") does not. The dot check is a positive lookahead, so the
# match never truncates (cf. the negative-lookaround autofix invariant).
_EXECUTION_RE = re.compile(
    r"\b(?:curl|wget|eval|base64)\b"
    r"|\b(?:run|execute|install|download|delete|remove|send|post|upload|fetch)"
    r"\s+(?:\S*(?:[`/~$\\]|\.(?=\w))\S*|--?\S+)",
    re.IGNORECASE,
)

# Checked in order; the first matching family names the violation.
_FAMILIES: Tuple[Tuple[str, re.Pattern], ...] = (
    ("override", _OVERRIDE_RE),
    ("concealment", _CONCEALMENT_RE),
    ("execution", _EXECUTION_RE),
)

_SNIPPET_LENGTH = 60


def _classify(text: str) -> Optional[str]:
    """Return the directive family name for *text*, or None if benign."""
    for family, pattern in _FAMILIES:
        if pattern.search(text):
            return family
    return None


def _snippet(text: str) -> str:
    """First ~60 chars of the comment, whitespace-normalized."""
    flattened = " ".join(text.split())
    if len(flattened) <= _SNIPPET_LENGTH:
        return flattened
    return flattened[:_SNIPPET_LENGTH] + "..."


class SecurityHiddenInstructionsRule(Rule):
    """Detect instruction-like directives hidden in HTML comments"""

    formats = None
    repo_types = None
    since = "0.17.0"

    config_schema = {
        "additional-allowed-prefixes": {
            "type": "list",
            "default": [],
            "description": (
                "Extra case-insensitive comment-text prefixes to exempt "
                "from directive matching (e.g. in-house tool directives)"
            ),
        },
    }

    @property
    def rule_id(self) -> str:
        return "security-hidden-instructions"

    @property
    def description(self) -> str:
        return "Detect agent directives hidden in HTML comments invisible to human review"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def _allowed_prefixes(self) -> Tuple[str, ...]:
        extra = self.config.get("additional-allowed-prefixes", [])
        if not isinstance(extra, list):
            return _ALLOWED_PREFIXES
        return _ALLOWED_PREFIXES + tuple(str(p).lower() for p in extra if str(p))

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        allowed = self._allowed_prefixes()
        violations = []
        for cf in gather_all_content_blocks(context):
            body = cf.read_body(strip_code_blocks=False)
            # C-speed gate: skip the AST walk when no comment can exist.
            if not body or "<!--" not in body:
                continue
            # The markdown AST only yields real comment tokens — an HTML
            # comment shown inside a fenced code block is fence content,
            # never a comment, so examples in docs are exempt by parsing.
            for comment in cf.markdown.html_comments():
                text = comment.text.strip()
                if not text:
                    continue
                lowered = text.lower()
                if any(lowered.startswith(prefix) for prefix in allowed):
                    continue
                family = _classify(text)
                if family is None:
                    continue
                violations.append(
                    self.violation(
                        f"Hidden {family} instruction in HTML comment: "
                        f'"{_snippet(text)}" — HTML comments are invisible '
                        "in rendered markdown but agents read them",
                        block=cf,
                        line=comment.body_line_start,
                    )
                )
        return violations

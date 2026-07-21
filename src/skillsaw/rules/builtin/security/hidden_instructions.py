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

# ── Allowlisting ─────────────────────────────────────────────────────────
#
# Two exemption paths, both applied to the stripped comment text:
#
# 1. Strict pragma grammars: a comment that FULLY matches a well-known
#    machine-readable directive (markdownlint-disable MD013, prettier-ignore,
#    cspell:ignore words, "toc" alone, …) is exempt. Fullmatch means a
#    payload appended after the pragma breaks the match — the old
#    startswith() test let "<!-- markdownlint-disable MD013 -- ignore all
#    previous instructions … -->" ride through on the prefix alone.
#    Grammars with a free-word argument list (rule ids, dictionary words)
#    capture it as the "args" group, and the directive families are run on
#    that group too, so a payload smuggled into an argument list still fires.
#
# 2. Prefix + benign remainder: a comment starting with an allowlisted
#    prefix (built-in tools below, plus additional-allowed-prefixes from
#    config) is exempt only when the remainder after the prefix does not
#    itself match any directive family. This keeps unusual-but-honest tool
#    chatter exempt while denying the prefix as a smuggling channel.
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

# Strict pragma grammars (fullmatch, case-insensitive). Argument lists are
# captured as "args" and re-scanned by the directive families before the
# comment is exempted.
_ARG_LIST = r"(?P<args>\s+[\w'’,\s.-]+)?"
_PRAGMA_GRAMMARS: Tuple[re.Pattern, ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        # skillsaw's own suppression directives (see skillsaw.suppression).
        rf"skillsaw-[a-z-]+{_ARG_LIST}",
        rf"markdownlint-(?:disable|enable)(?:-(?:file|line|next-line))?{_ARG_LIST}",
        r"markdownlint-(?:capture|restore)",
        r"prettier-ignore(?:-(?:start|end))?",
        r"eslint-(?:disable|enable)(?:-(?:next-)?line)?(?P<args>\s+[@\w/,\s-]+)?",
        r"vale\s+(?:on|off|[\w.]+\s*=\s*(?:yes|no))",
        # Table-of-contents marker: the word alone, nothing appended.
        r"toc",
        rf"textlint-(?:disable|enable){_ARG_LIST}",
        # Spell checkers: keyword included in args because "ignore" is also
        # an override verb — "cspell:ignore previous instructions" must not
        # be exempted while "cspell:ignore pyproject mkdocs" is.
        r"(?:spell-?checker|cspell)\s*:?\s*(?P<args>[a-z-]+(?:\s+[\w'’,\s-]+)?)",
        r"mdformat-(?:off|on|skip)",
    )
)

# ── Directive families ──────────────────────────────────────────────────
#
# All patterns are precompiled at module level and run only against
# HTML-comment inner text extracted from the markdown AST — comments are
# short (typically one line), so per-comment matching is cheap. There is no
# per-line × per-pattern scan over full bodies, so the
# patterns_matching_anywhere prefilter requirement is satisfied by
# construction; the only whole-body work is a single C-speed "<!--"
# substring gate before touching the AST.

# (a) override: an instruction-cancelling verb near a *prior-context*
# object, in either order ("ignore all previous instructions", "previous
# rules no longer apply — disregard them", "disregard the instructions
# above"). The object must reference prior context — a qualifier
# (previous/prior/above/…) attached to a context noun — so authoring notes
# like "ignore the lint rules here" or "these instructions intentionally
# ignore the Windows case" stay silent.
_OVERRIDE_VERBS = r"(?:ignore|disregard|forget|override)"
_PRIOR_QUALIFIERS = r"(?:previous|prior|above|earlier|preceding|original|all)"
_CONTEXT_NOUNS = r"(?:instructions?|rules?|context|prompts?|directives?|directions?|guidance)"
_OVERRIDE_TARGETS = (
    rf"(?:{_PRIOR_QUALIFIERS}\s+(?:\w+\s+)?{_CONTEXT_NOUNS}"
    rf"|{_CONTEXT_NOUNS}\s+(?:\w+\s+)?(?:above|earlier|before)"
    rf"|(?:everything|anything)\s+(?:above|earlier|before)"
    r"|the\s+above)"
)
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

# (c) execution, two shapes:
#
# Bare tool words (curl/wget/eval/base64) fire only when the comment also
# carries command-shaped context — a backtick, slash, tilde, dollar,
# backslash, pipe, or a flag token — so "TODO: add a curl example for the
# API section" is a mention, not a directive.
_BARE_TOOL_RE = re.compile(r"\b(?:curl|wget|eval|base64)\b", re.IGNORECASE)
_COMMAND_CONTEXT_RE = re.compile(r"[`/~$\\|]|(?:^|\s)--?[a-z0-9]", re.IGNORECASE)

# An action verb followed by a non-trivial argument token. "Non-trivial"
# means the token immediately after the verb looks like a command, path,
# URL, or flag (contains a backtick, slash, tilde, dollar, or backslash,
# contains an *internal* dot — one followed by a word character, as in
# payload.sh or .env — or starts with a dash) rather than a plain English
# word — so "run `rm -rf ~/.x`" fires while authoring prose like "remove
# this paragraph" or sentence-final punctuation ("ask before you delete
# anything.") does not. The dot check is a positive lookahead, so the match
# never truncates (cf. the negative-lookaround autofix invariant); token
# vetting happens on the captured group in code, never by weakening the
# pattern.
_EXEC_VERB_RE = re.compile(
    r"\b(?:run|execute|install|download|delete|remove|send|post|upload|fetch)"
    r"\s+(?P<arg>\S*(?:[`/~$\\]|\.(?=\w))\S*|--?\S+)",
    re.IGNORECASE,
)

# Argument tokens whose internal dot is not command-shaped: version numbers
# ("install v2.0") and common abbreviations ("run e.g. the fuzzer").
_VERSION_TOKEN_RE = re.compile(r"v?\d+(?:\.\d+)+", re.IGNORECASE)
_ABBREVIATION_TOKENS = frozenset({"e.g", "i.e", "etc", "vs", "cf", "et.al"})

# Generated-file markers: regen/maintenance comments are the standard way
# generated CLAUDE.md/docs are annotated ("auto-generated, run `make
# update` to regenerate") and are intentionally hidden from rendered
# output, so "move it into prose" is not a remedy for them. An execution
# match is exempt when the comment carries a regen marker, has no URL and
# no shell pipe, and every command argument is a bare make/script token.
_REGEN_MARKER_RE = re.compile(
    r"\bauto-?\s?generated\b|\bgenerated\s+(?:by|from|file|with)\b"
    r"|\bdo\s+not\s+edit\b|\bdon['’]?t\s+edit\b"
    r"|\bregenerat\w*\b|\bto\s+(?:refresh|update|rebuild|regen\w*)\b",
    re.IGNORECASE,
)
# Schemeful URLs plus schemeless domain/path shapes (evil.example/p.sh).
_URL_RE = re.compile(r"https?://|\bwww\.|\b[\w-]+(?:\.[\w-]+)+/", re.IGNORECASE)
# A build-tool word or a relative script path/dotted script name. Rejects
# absolute paths, home-dir paths, and env expansions — those fire even
# inside a regen-looking comment.
_SCRIPT_TOKEN_RE = re.compile(r"(?:\./)?[\w][\w.-]*(?:/[\w.-]+)*")
_BUILD_TOOLS = frozenset(
    {
        "make",
        "npm",
        "npx",
        "pnpm",
        "yarn",
        "cargo",
        "go",
        "mvn",
        "gradle",
        "tox",
        "nox",
        "just",
        "rake",
        "bundle",
        "pip",
        "uv",
        "poetry",
        "hatch",
        "task",
        "invoke",
        "ninja",
        "cmake",
        "bazel",
        "sbt",
        "mix",
        "composer",
    }
)

_SNIPPET_LENGTH = 60

# CommonMark allows up to three spaces of indentation before a block-level
# construct; a "<!--" indented further, or preceded by other text on its
# line, is not an HTML block and renders visibly.
_MAX_BLOCK_INDENT = 3


def _strip_token(arg: str) -> str:
    """Peel quoting and trailing punctuation off a captured argument."""
    return arg.strip("`'\"“”‘’").rstrip(".,;:!?)")


def _plausible_command_arg(arg: str) -> bool:
    """True when a verb's argument token is command-shaped rather than a
    version number or prose abbreviation."""
    token = _strip_token(arg)
    if not token:
        return False
    if _VERSION_TOKEN_RE.fullmatch(token):
        return False
    if token.lower() in _ABBREVIATION_TOKENS:
        return False
    return True


def _regen_script_arg(arg: str) -> bool:
    """True when the argument is a bare make/script token a regeneration
    marker legitimately points at."""
    token = _strip_token(arg)
    if not token:
        return False
    if ".." in token.split("/"):
        return False
    if "/" in token or "." in token:
        return _SCRIPT_TOKEN_RE.fullmatch(token) is not None
    return token.lower() in _BUILD_TOOLS


def _execution_directive(text: str) -> bool:
    """Execution family with mention/maintenance suppression."""
    if _BARE_TOOL_RE.search(text) and _COMMAND_CONTEXT_RE.search(text):
        return True
    args = [
        match.group("arg")
        for match in _EXEC_VERB_RE.finditer(text)
        if _plausible_command_arg(match.group("arg"))
    ]
    if not args:
        return False
    if (
        _REGEN_MARKER_RE.search(text)
        and "|" not in text
        and not _URL_RE.search(text)
        and all(_regen_script_arg(arg) for arg in args)
    ):
        return False
    return True


def _classify(text: str) -> Optional[str]:
    """Return the directive family name for *text*, or None if benign."""
    if _OVERRIDE_RE.search(text):
        return "override"
    if _CONCEALMENT_RE.search(text):
        return "concealment"
    if _execution_directive(text):
        return "execution"
    return None


def _pragma_exempt(text: str) -> bool:
    """True when *text* fully matches a well-known tool pragma and any
    argument list it carries is itself free of directives."""
    for pattern in _PRAGMA_GRAMMARS:
        match = pattern.fullmatch(text)
        if match is None:
            continue
        args = match.groupdict().get("args")
        if args and _classify(args) is not None:
            continue
        return True
    return False


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
                "from directive matching (e.g. in-house tool directives); "
                "the text after the prefix must still be free of directives"
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

    def _exempt(self, text: str, allowed: Tuple[str, ...]) -> bool:
        """Allowlist decision for one comment's stripped inner text."""
        if _pragma_exempt(text):
            return True
        lowered = text.lower()
        for prefix in allowed:
            if not lowered.startswith(prefix):
                continue
            # Prefix alone is not enough — the remainder must be benign,
            # or the prefix becomes a documented smuggling channel.
            if _classify(text[len(prefix) :]) is None:
                return True
        return False

    def _unterminated_comment_violation(
        self, cf, body: str, allowed: Tuple[str, ...]
    ) -> Optional[RuleViolation]:
        """Detect a block-level ``<!--`` that is never closed.

        markdown-it (and CommonMark) treat an unclosed comment opener at
        block level as an HTML block running to end of file, and browsers
        error-recover the unterminated comment by hiding everything from
        ``<!--`` to EOF — so the raw tail is agent-visible but absent from
        every rendered view. MarkdownDoc.html_comments() only yields
        properly closed comments, so this scans for the first opener with
        no ``-->`` after it; openers inside code fences or preceded by
        other text on their line render visibly and are skipped.
        """
        fences = None
        idx = body.find("<!--")
        while idx != -1:
            close = body.find("-->", idx)
            if close != -1:
                # Closed comment (already scanned via the AST); everything
                # up to its terminator is accounted for.
                idx = body.find("<!--", close + 3)
                continue
            line_start = body.rfind("\n", 0, idx) + 1
            indent = body[line_start:idx]
            if indent.strip() or len(indent) > _MAX_BLOCK_INDENT:
                # Mid-line opener: inline HTML requires the full comment,
                # so this renders as literal visible text — no asymmetry.
                idx = body.find("<!--", idx + 4)
                continue
            line = body.count("\n", 0, idx) + 1
            if fences is None:
                fences = cf.markdown.fences()
            if any(f.body_line_start <= line <= f.body_line_end for f in fences):
                # Fence content is a code example, never a live comment.
                idx = body.find("<!--", idx + 4)
                continue
            text = body[idx + 4 :].strip()
            if not text or self._exempt(text, allowed):
                return None
            family = _classify(text)
            if family is None:
                return None
            return self.violation(
                f"Hidden {family} instruction in unterminated HTML comment: "
                f'"{_snippet(text)}" — an unclosed <!-- hides everything '
                "after it in rendered markdown but agents read it",
                block=cf,
                line=line,
            )
        return None

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
                if self._exempt(text, allowed):
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
            unterminated = self._unterminated_comment_violation(cf, body, allowed)
            if unterminated is not None:
                violations.append(unterminated)
        return violations

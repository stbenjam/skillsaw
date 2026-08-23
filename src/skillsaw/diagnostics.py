"""Making untrusted values safe to echo into violation messages.

Any rule that quotes a manifest or config value in a diagnostic routes
it through here, whatever ecosystem the rule belongs to.
"""

from __future__ import annotations

import re

# C0, DEL, C1, lone UTF-16 surrogate code points, and the Unicode bidi
# overrides — any of them can reorder or hide message text in a terminal or
# a rendered SARIF viewer. Surrogates also cannot be encoded as UTF-8, so a
# JSON key containing an escaped lone surrogate must never reach a formatter.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f\ud800-\udfff\u202a-\u202e\u2066-\u2069]")

# Everything a message needs to locate the defect fits comfortably here;
# an adversarial multi-kilobyte value must not become a multi-kilobyte
# diagnostic in a CI artifact.
_MAX_DISPLAY = 500

# How far past a cut or an ``@`` the scanners will look before giving up
# and erring toward redaction. Bounds the work on adversarial input.
_LOOKAHEAD = 512


def _redact_userinfo(text: str) -> str:
    """Strip credential-shaped userinfo before every ``@`` in *text*.

    Covers scheme-full ("https://u:tok@h/x"), scheme-relative, bare
    ("u:tok@h/x"), and scp-style ("tok@github.com:o/r.git") spellings:
    the segment between the last ``/``/whitespace and an ``@`` is
    redacted when it carries a colon (credential shape) or when the text
    after the ``@`` looks host-like (a dot or colon before the next
    whitespace). Over-redacting an email-shaped value in a path field is
    the safe direction. A linear right-to-left scan — no regex, so there
    is nothing to backtrack, and no length cap for a long token to slip
    past. A backslash-newline pair is skipped rather than treated as a
    boundary: the shell joins continuation lines into one word, so
    splitting a credential across one must not end the scan.
    """
    if "@" not in text:
        return text
    out = []
    emitted = 0
    search_from = 0
    length = len(text)
    while True:
        at = text.find("@", search_from)
        if at == -1:
            out.append(text[emitted:])
            return "".join(out)
        # The backward window is floored like the forward host cap below:
        # without it, a delimiter-free prefix is rescanned for every ``@``
        # and the scan goes quadratic on adversarial input. When the
        # clipped window holds no delimiter the credential may extend past
        # it, so redact from the last emit point — never clamp ``start``
        # into the middle of a secret and emit its head.
        floor = max(emitted, at - 512)
        found = max(text.rfind(ch, floor, at) for ch in ("/", " ", "\t", "\n", "@"))
        # A backslash-newline is a line continuation, not a token boundary:
        # the shell joins the lines into one word, so a credential split
        # across one ("user:tok\<newline>123@host") is a single userinfo
        # segment. Skip the pair and keep scanning; each round strictly
        # lowers the bound, so the loop terminates.
        while found > 0 and text[found] == "\n" and text[found - 1] == "\\":
            found = max(text.rfind(ch, floor, found - 1) for ch in ("/", " ", "\t", "\n", "@"))
        start = found + 1 if found != -1 else emitted
        userinfo = text[start:at]
        if not userinfo:
            search_from = at + 1
            continue
        # Host inspection is capped: a host longer than any real one with
        # no whitespace is treated as host-like, which errs toward
        # redaction — the safe direction.
        head_limit = min(at + 1 + 512, length)
        host_head = text[at + 1 : head_limit]
        # Same continuation rule looking forward: "tok@exa\<newline>mple.com"
        # is one host word, and stopping at the newline would hide the dot
        # that makes it host-like.
        ws = None
        index = 0
        while index < len(host_head):
            char = host_head[index]
            if char == "\\" and host_head.startswith("\n", index + 1):
                index += 2
                continue
            if char.isspace():
                ws = index
                break
            index += 1
        if ws is not None:
            host_head = host_head[:ws]
            host_like = "." in host_head or ":" in host_head
        else:
            host_like = "." in host_head or ":" in host_head or head_limit < length
        if ":" in userinfo or host_like:
            out.append(text[emitted:start])
            out.append("[redacted]")
            emitted = at
        search_from = at + 1


def _cut_severed_userinfo(raw: str, cut: int) -> bool:
    """Whether truncating *raw* at *cut* split a credential before its ``@``.

    A colon-free token — ``https://<600 chars of token>@host`` — leaves a
    displayed tail with nothing credential-shaped about it, so the
    colon test alone waves the token straight through. Looking past the
    cut settles it: an ``@`` reached before any delimiter means the
    visible tail is the head of some userinfo.

    The lookahead is capped for the same reason the caller truncates at
    all. Running past the cap without resolving it means the segment is
    longer than any real path component, which is treated as
    credential-shaped — the safe direction, matching the host-length cap
    in :func:`_redact_userinfo`. Backslash-newline pairs are skipped, not
    boundaries: a continuation joins the tail to the head before the cut.
    """
    window = raw[cut : cut + _LOOKAHEAD]
    index = 0
    while index < len(window):
        char = window[index]
        if char == "\\" and window.startswith("\n", index + 1):
            index += 2
            continue
        if char == "@":
            return True
        if char in "/ \t\n":
            return False
        index += 1
    return len(raw) > cut + _LOOKAHEAD


def encodable(text: str) -> str:
    """*text* with anything UTF-8 cannot encode written as an escape.

    The last line of defence for a whole rendered report, not a substitute
    for :func:`safe_display` on individual values — it neither truncates
    nor redacts, because a report is not an untrusted scalar and must come
    out whole.

    A rule can only sanitize a value it knows is hostile. JSON decodes
    ``"\\ud800"`` to an unpaired surrogate, which any rule may then quote
    into a message from a source it has no reason to distrust — and the
    encode that follows raises ``UnicodeEncodeError``, losing the entire
    report over one character. ``backslashreplace`` keeps the codepoint
    legible rather than dropping it.
    """
    return text.encode("utf-8", "backslashreplace").decode("utf-8")


def terminal_safe(value: object) -> str:
    """Return complete text with terminal control characters neutralized.

    Unlike :func:`safe_display`, this last-line formatter guard does not
    truncate or redact a complete diagnostic. It only prevents repository
    content from injecting terminal controls, bidi overrides, or unencodable
    surrogate code points into human-readable output.
    """
    # Preserve lone surrogates as their visible ``\\ud800`` spelling, matching
    # the report-wide encoding guard, while replacing executable terminal
    # controls and bidi overrides with a single harmless glyph.
    return _CONTROL_CHARS.sub("\N{REPLACEMENT CHARACTER}", encodable(str(value)))


def _truncate_for_display(raw: str) -> str:
    """*raw* cut to the display cap, with a severed credential redacted.

    The cut can sever a credential ahead of its ``@``, leaving a window
    that redaction would never match. Two ways to tell: the visible tail
    is colon-bearing (``user:token`` shape), or the ``@`` itself sits just
    past the cut. Over-redacting a truncated tail is the safe direction.

    The backward boundary walk skips backslash-newline pairs, exactly as
    the redaction scan does: a continuation joins the words around it, so
    a credential severed mid-token *after* a continuation must redact the
    fragment before the split too — stopping at the newline would leave
    ``user:token`` visible ahead of it.
    """
    text = raw[:_MAX_DISPLAY]
    if len(text) == len(raw):
        return text
    end = len(text)
    while True:
        found = max(text.rfind(ch, 0, end) for ch in ("/", " ", "\t", "\n", "@"))
        if found == -1:
            break
        if text[found] == "\n" and found > 0 and text[found - 1] == "\\":
            end = found - 1
            continue
        break
    start = found + 1
    if ":" in text[start:] or _cut_severed_userinfo(raw, _MAX_DISPLAY):
        text = text[:start] + "[redacted]"
    return text


def safe_display(value: object) -> str:
    """A manifest value made safe to echo into a violation message.

    Reports are uploaded as CI artifacts and ingested as SARIF, so an
    author's pasted ``user:token@host`` URL must not ride along — the
    userinfo is redacted, keeping the locator. Control characters and
    unencodable lone surrogates are replaced so a crafted value cannot
    smuggle terminal escapes through or crash a formatter, and the result is
    length-bounded.
    """
    raw = str(value)
    truncated = len(raw) > _MAX_DISPLAY
    # Truncate before scanning so the display cap bounds the *work*, not
    # just the output — redaction over the full value is superlinear
    # on adversarial input (a megabyte of "a:b@" costs seconds), and one
    # diagnostic must not buy minutes of CPU.
    text = _truncate_for_display(raw)
    text = _CONTROL_CHARS.sub("\N{REPLACEMENT CHARACTER}", text)
    text = _redact_userinfo(text)
    if truncated or len(text) > _MAX_DISPLAY:
        text = text[:_MAX_DISPLAY] + "…"
    return text

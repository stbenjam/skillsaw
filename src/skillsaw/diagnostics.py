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
    past.
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
        ws = next((i for i, ch in enumerate(host_head) if ch.isspace()), None)
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
    # just the output — redaction over the full value is quadratic-ish in
    # the worst case, and a multi-megabyte manifest value must not buy
    # minutes of CPU for one diagnostic.
    text = raw[:_MAX_DISPLAY]
    if truncated:
        # The cut can sever a credential ahead of its ``@`` — the window
        # then holds a bare colon-bearing segment redaction would never
        # match. Treat the cut like an ``@``: redact a colon-bearing tail
        # segment. Over-redacting a truncated tail is the safe direction.
        start = max(text.rfind(ch) for ch in ("/", " ", "\t", "\n", "@")) + 1
        if ":" in text[start:]:
            text = text[:start] + "[redacted]"
    text = _CONTROL_CHARS.sub("\N{REPLACEMENT CHARACTER}", text)
    text = _redact_userinfo(text)
    if truncated or len(text) > _MAX_DISPLAY:
        text = text[:_MAX_DISPLAY] + "…"
    return text

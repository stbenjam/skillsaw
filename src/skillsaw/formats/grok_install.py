"""Grok Build 1.0.13's effective Git install pin, separate from display SHA."""

from typing import Optional, Tuple

from skillsaw.formats.grok import SHA_RE

# Rust str::trim uses Unicode White_Space. Python's default str.strip also
# removes U+001C..U+001F, which must not make a malformed SHA look pinned.
_RUST_WHITESPACE = (
    "\t\n\v\f\r \x85\xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005"
    "\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000"
)


def effective_install_pin(
    git_ref: Optional[str], git_sha: Optional[str]
) -> Tuple[str, Optional[str]]:
    """Return the authored field and trimmed pin after typed catalog decoding.

    Mirrors hoist_pin_slots: any explicit SHA takes precedence, including
    an invalid or empty one. Only a full commit ref is hoisted when SHA is
    absent/null. Ordinary refs remain unpinned.
    """
    if git_sha is not None:
        return "sha", git_sha.strip(_RUST_WHITESPACE)
    if git_ref is not None:
        pin = git_ref.strip(_RUST_WHITESPACE)
        if SHA_RE.fullmatch(pin):
            return "ref", pin
    return "sha", None

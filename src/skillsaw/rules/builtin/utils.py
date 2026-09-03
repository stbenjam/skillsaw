"""Shared YAML/JSON/text helpers for the rule layer.

Most of the implementation moved to the core :mod:`skillsaw.utils` module so
that core modules (``blocks``, ``context``, ``lint_tree``) can use it without
importing this rule package (which would invert the layering and create an
import cycle).  Rule modules, custom rules, and tests that still do
``from skillsaw.rules.builtin.utils import ...`` keep working unchanged via
the re-exports below.

Helpers that only the rules need — the strict-JSON reader below, which
several ecosystems (Codex, Agent Plugins) each require in exactly the same
form, and the Rust-dialect regex check two hooks rules share — live here
rather than in core, so no ecosystem package has to import another
ecosystem's private helpers to reuse them.
"""

import json
import re
import warnings
from pathlib import Path
from typing import Any, List, Optional, Tuple

from skillsaw.utils import *  # noqa: F401,F403
from skillsaw.utils import (  # noqa: F401  — underscore names ``*`` does not re-export
    _FRONTMATTER_RE,
    _extract_frontmatter_text,
    _fast_top_level_key_lines,
    reject_duplicate_json_keys,
)
from skillsaw.utils import read_text


def reject_nonfinite_json_number(value: str) -> None:
    """Reject JavaScript number extensions that strict JSON does not allow.

    ``json.loads`` accepts ``NaN``/``Infinity``/``-Infinity`` by default; the
    strict parsers the specs describe do not.  Passed as ``parse_constant`` so
    validity rules and fixers reject exactly the same documents.
    """
    raise ValueError(f"non-finite JSON number: {value}")


def strict_json(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    """Parse a UTF-8 document as strict JSON without network access."""
    content = read_text(path)
    if content is None:
        return None, "could not read file"
    try:
        return (
            json.loads(
                content,
                parse_constant=reject_nonfinite_json_number,
                object_pairs_hook=reject_duplicate_json_keys,
            ),
            None,
        )
    except json.JSONDecodeError as error:
        return None, f"{error.msg} at line {error.lineno}, column {error.colno}"
    except ValueError as error:
        return None, str(error)
    except RecursionError:
        return None, "JSON nesting is too deep"


#: Unicode character classes: ``\p{Greek}``, ``\pL`` and their negations.
#: Rust's ``regex`` crate compiles these and Python's ``re`` raises on them.
#: The braced name is bounded: no Unicode script or property name comes near
#: 64 characters, and an unbounded run inside an untrusted matcher is work
#: this check has no reason to accept. A longer run simply does not match, so
#: the ``\p`` survives into ``re.compile`` and is reported as it was before.
_RUST_UNICODE_CLASS = re.compile(r"\\[pP](?:\{[^}]{0,64}\}|[A-Za-z])")

#: Rust's character-class set operators: ``[a-z&&[^aeiou]]``,
#: ``[\w--\d]``, ``[a-g~~b-h]``. Python has no equivalent syntax.
_RUST_CLASS_SET_OPERATOR = re.compile(r"&&|--|~~")

#: A Rust named capture group: ``(?<tool>Bash|Write)``, which Grok Build
#: 1.0.13 loads. Python spells the same thing ``(?P<tool>...)`` and raises
#: "unknown extension ?<t" on Rust's — so without this rewrite a working
#: matcher is reported as broken.
#:
#: The ``(?![=!])`` is the seam with :data:`_RUST_UNSUPPORTED_CANDIDATE`:
#: ``(?<=`` and ``(?<!`` are look-behind, which Rust does *not* have, and
#: those two spellings are that table's to report. The two must agree on
#: which ``(?<`` is which, or a look-behind is silently rewritten into a
#: group name and passes.
_RUST_NAMED_GROUP = re.compile(r"\(\?<(?![=!])")

#: The constructs the compile check alone cannot see: Python's ``re``
#: accepts them and Rust's ``regex`` crate — a finite-automaton engine —
#: refuses them, so the host drops the matcher group while ``re.compile``
#: reports nothing. Verified against Grok Build 1.0.13, where ``(?<=x)y`` and
#: ``(a)\1`` each dropped their group.
#:
#: Group openings: the four look-around spellings, ``(?P=name)`` (Python's
#: named backreference), and the conditional, comment and atomic group kinds
#: (``(?(``, ``(?#``, ``(?>``). ``(?<name>...)`` is a *named group* in Rust
#: and is deliberately absent — only ``(?<=`` and ``(?<!`` are look-around.
#: Escapes: ``\1``…``\9``, ``\k<name>`` and ``\Z``.
#:
#: A match here is a *candidate*, not a verdict: :func:`_rust_unsupported`
#: re-walks the pattern to drop one that is escaped (``\(?=``) or inside a
#: character class (``[(?=]``), both of which are literal text.
_RUST_UNSUPPORTED_CANDIDATE = re.compile(r"\(\?(?:<[=!]|[=!]|P=|[(#>])|\\(?:[1-9]|k<|Z)")

#: What :func:`rust_matcher_error` reports for each, phrased to follow the
#: hosts' "does not compile: ".
_NO_LOOK_AROUND = "Rust's regex has no look-around"
_NO_BACKREFERENCES = "Rust's regex has no backreferences"
#: Rust's end-of-text anchor is ``\z`` alone; Python's ``\Z`` spelling is an
#: unrecognized escape there (verified: Grok 1.0.13 drops the hook).
_NO_UPPER_Z = "Rust's regex has no \\Z anchor (write \\z)"
#: The three remaining ``(?`` group kinds Python has and Rust does not
#: (verified: Grok 1.0.13 drops a hook carrying any of them).
_NO_CONDITIONALS = "Rust's regex has no conditional groups"
_NO_COMMENTS = "Rust's regex has no comment groups"
_NO_ATOMIC_GROUPS = "Rust's regex has no atomic groups"

#: Longest matcher :func:`rust_matcher_error` will compile-check. A hooks
#: file is untrusted input and the check translates the matcher — a few
#: regex passes and a character walk — before handing it to ``re.compile``, whose
#: own parser is where a pathological pattern gets expensive. A real matcher
#: names tools (``Write|Edit|Bash``), so the cap is orders of magnitude above
#: anything an author writes. Past it the caller is told *nothing* rather
#: than "too long": no host imposes a length limit, so length is not a
#: defect and a finding for it would be a false positive.
RUST_MATCHER_MAX_LENGTH = 1000


def _to_python_regex(pattern: str) -> str:
    """*pattern* with Rust-only atoms rewritten to Python-compatible ones.

    Muse Code and Grok Build both compile a hook matcher with the Rust
    ``regex`` crate, whose dialect is not Python's: it has no look-around and
    no backreferences (:func:`_rust_unsupported` owns that direction), and it
    has four constructs a hooks file plausibly reaches that Python spells
    differently, not at all, or only on newer interpreters — Unicode
    character classes, the character-class set operators, the
    ``(?<name>...)`` capture group, and the ``\\z`` end-of-string anchor.
    Python raises on each unrewritten (``\\z`` on every Python before
    3.14), so compiling the pattern as written would call a working matcher
    broken. Skipping such a pattern instead would drop every other defect in
    it: ``(\\pL`` leaves a group unclosed, which costs the matcher group
    whatever engine reads it.

    So the Rust-only atoms are substituted rather than the check skipped —
    ``\\p{...}`` and its short forms become ``\\w``, ``(?<name>`` becomes
    Python's ``(?P<name>``, the set operators are dropped, an unescaped
    ``\\z`` becomes ``\\Z`` (the same anchor, accepted on every supported
    Python) — and what is left is the structure both dialects share. The
    reverse spelling is not shared: Rust has no ``\\Z``, and
    :func:`_rust_unsupported` reports one before the rewrite would mask it.
    """
    substituted = _RUST_UNICODE_CLASS.sub(r"\\w", pattern)
    if "(?<" in substituted:
        substituted = _RUST_NAMED_GROUP.sub("(?P<", substituted)
    if "[" not in substituted and "\\z" not in substituted:
        return substituted

    # The set operators only mean anything inside a character class: ``a--b``
    # outside one is three literal characters in either dialect. ``\z`` is
    # rewritten only outside a class: inside one neither dialect accepts it
    # (Grok 1.0.13 drops the hook, Python raises ``bad escape``), so it is
    # left for the compile to report. Escapes are consumed whole so a
    # ``\[`` does not open a class and a preceding backslash (``\\z``, a
    # literal backslash then ``z``) is never mistaken for the anchor.
    out: List[str] = []
    depth = 0
    index = 0
    end = len(substituted)
    while index < end:
        char = substituted[index]
        if char == "\\":
            following = substituted[index + 1 : index + 2]
            if not depth and following == "z":
                out.append("\\Z")
            else:
                out.append(substituted[index : index + 2])
            index += 2
            continue
        if depth:
            operator = _RUST_CLASS_SET_OPERATOR.match(substituted, index)
            if operator is not None:
                index = operator.end()
                continue
        if char == "[":
            depth += 1
        elif char == "]" and depth:
            depth -= 1
        out.append(char)
        index += 1
    return "".join(out)


def _rust_unsupported(pattern: str) -> Optional[str]:
    """Why Rust refuses *pattern* where Python would compile it, if it does.

    Look-around, backreferences, the ``\\Z`` anchor, and the conditional,
    comment and atomic group kinds are the whole list of *constructs*:
    everything else Python accepts is either shared with Rust or already
    caught by the compile. Possessive quantifiers (``a++``, Python 3.11+)
    are the one omission — naming them means parsing quantifiers, and no
    hooks file has carried one.

    :data:`_RUST_UNSUPPORTED_CANDIDATE` is the gate, so a matcher without one
    of those runs never reaches the walk. A hit is then confirmed by walking
    the pattern the way :func:`_to_python_regex` does — escapes consumed
    whole, character-class depth tracked — because ``\\(?=`` and ``[(?=]`` are
    literal text in both dialects and reporting either would be a false
    positive. The walk is deliberately simple, so it misses a construct a
    fuller parser would see (a backreference inside a class, say). Under-
    reporting leaves the matcher checked exactly as it was before; over-
    reporting would call a working matcher broken.
    """
    if _RUST_UNSUPPORTED_CANDIDATE.search(pattern) is None:
        return None

    depth = 0
    index = 0
    end = len(pattern)
    while index < end:
        char = pattern[index]
        if char == "\\":
            if not depth:
                following = pattern[index + 1 : index + 2]
                if following and following in "123456789":
                    return _NO_BACKREFERENCES
                if following == "k" and pattern[index + 2 : index + 3] == "<":
                    return _NO_BACKREFERENCES
                if following == "Z":
                    return _NO_UPPER_Z
            index += 2
            continue
        if char == "[":
            depth += 1
        elif char == "]" and depth:
            depth -= 1
        elif char == "(" and not depth:
            opening = pattern[index + 1 : index + 4]
            if opening.startswith(("?=", "?!", "?<=", "?<!")):
                return _NO_LOOK_AROUND
            if opening.startswith("?P="):
                return _NO_BACKREFERENCES
            if opening.startswith("?("):
                return _NO_CONDITIONALS
            if opening.startswith("?#"):
                return _NO_COMMENTS
            if opening.startswith("?>"):
                return _NO_ATOMIC_GROUPS
        index += 1
    return None


def rust_matcher_error(matcher: str) -> Optional[str]:
    """Why *matcher* fails to compile as a Rust regex, if it does.

    ``None`` when the pattern compiles, when it is longer than
    :data:`RUST_MATCHER_MAX_LENGTH`, or when what fails is a construct Rust
    accepts and Python does not. A host that compiles hook matchers with the
    Rust ``regex`` crate — Muse Code, Grok Build — drops the matcher group
    when this returns a string, and nothing else in the file.

    Two verdicts, because the dialects diverge in both directions. Python
    rejecting the pattern is one; the other is a construct Python *accepts*
    and Rust does not — look-around, backreferences, ``\\Z``, conditional,
    comment and atomic groups — which the compile can never see, so
    :func:`_rust_unsupported` runs first.
    """
    if len(matcher) > RUST_MATCHER_MAX_LENGTH:
        return None
    unsupported = _rust_unsupported(matcher)
    if unsupported is not None:
        return unsupported
    try:
        # Rewritten, not skipped: a pattern carrying a Rust-only atom still
        # has the structure both dialects share, and an unclosed group costs
        # the matcher group whatever engine reads it.
        #
        # A POSIX class Rust accepts (``[[:alpha:]]+``) makes CPython emit
        # ``FutureWarning: Possible nested set`` — a warning the ``except``
        # below cannot catch, printed into the middle of the lint report for
        # a matcher that works.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            re.compile(_to_python_regex(matcher))
    except (re.error, RecursionError, OverflowError) as err:
        return getattr(err, "msg", None) or str(err)
    return None

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

#: Longest matcher :func:`rust_matcher_error` will compile-check. A hooks
#: file is untrusted input and the check translates the matcher — two regex
#: passes and a character walk — before handing it to ``re.compile``, whose
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
    no backreferences, and it adds two constructs a hooks file plausibly
    reaches — Unicode character classes and the character-class set
    operators. Python raises on both, so compiling the pattern as written
    would call a working matcher broken. Skipping such a pattern instead
    would drop every other defect in it: ``(\\pL`` leaves a group unclosed,
    which costs the matcher group whatever engine reads it.

    So the Rust-only atoms are substituted rather than the check skipped —
    ``\\p{...}`` and its short forms become ``\\w``, the set operators are
    dropped — and what is left is the structure both dialects share.
    """
    substituted = _RUST_UNICODE_CLASS.sub(r"\\w", pattern)
    if "[" not in substituted:
        return substituted

    # The set operators only mean anything inside a character class: ``a--b``
    # outside one is three literal characters in either dialect. Escapes are
    # consumed whole so a ``\[`` does not open a class.
    out: List[str] = []
    depth = 0
    index = 0
    end = len(substituted)
    while index < end:
        char = substituted[index]
        if char == "\\":
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


def rust_matcher_error(matcher: str) -> Optional[str]:
    """Why *matcher* fails to compile as a Rust regex, if it does.

    ``None`` when the pattern compiles, when it is longer than
    :data:`RUST_MATCHER_MAX_LENGTH`, or when what fails is a construct Rust
    accepts and Python does not. A host that compiles hook matchers with the
    Rust ``regex`` crate — Muse Code, Grok Build — drops the matcher group
    when this returns a string, and nothing else in the file.
    """
    if len(matcher) > RUST_MATCHER_MAX_LENGTH:
        return None
    try:
        # Rewritten, not skipped: a pattern carrying a Rust-only atom still
        # has the structure both dialects share, and an unclosed group costs
        # the matcher group whatever engine reads it.
        re.compile(_to_python_regex(matcher))
    except (re.error, RecursionError, OverflowError) as err:
        return getattr(err, "msg", None) or str(err)
    return None

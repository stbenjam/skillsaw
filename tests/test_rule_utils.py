"""Direct unit tests for ``skillsaw.rules.builtin.utils``'s shared helpers.

``rust_matcher_error()`` is a public helper two rules share
(``muse-hooks-valid``, ``grok-hooks-valid``) but had no test of its own —
only end-to-end coverage through those two rules, which never pins the
length-cap boundary independently of whatever pattern size each rule's own
tests happen to use. These tests pin the helper's contract directly: every
construct Rust accepts and Python does not, every construct Python accepts
and Rust does not (correctly named), the ``(?<name>...)`` /
``(?<=``/``(?<!`` seam the helper's docstring calls out, the length cap, and
the ``\\z`` anchor rewrite.
"""

from __future__ import annotations

import pytest

from skillsaw.rules.builtin.utils import (
    RUST_MATCHER_MAX_LENGTH,
    _to_python_regex,
    rust_matcher_error,
)

# ── Constructs Rust's `regex` crate accepts that Python's `re` does not ──


@pytest.mark.parametrize(
    "pattern",
    [
        r"\p{L}+",
        r"\p{Greek}",
        r"\pL",
        r"[a-z&&[^aeiou]]",
        r"[\w--\d]",
        r"[a-g~~b-h]",
        r"(?<tool>Bash|Write)",
        r"Bash|Write",
    ],
)
def test_a_rust_only_construct_compiles(pattern) -> None:
    """Rewritten to a Python-compatible spelling rather than reported as
    broken — these are all constructs Grok Build and Muse Code accept."""
    assert rust_matcher_error(pattern) is None


# ── Constructs Python's `re` accepts that Rust's `regex` crate does not ──


@pytest.mark.parametrize(
    ("pattern", "message"),
    [
        (r"(?<=x)y", "Rust's regex has no look-around"),
        (r"(?<!x)y", "Rust's regex has no look-around"),
        (r"(?=Write)Bash", "Rust's regex has no look-around"),
        (r"(?!Write)Bash", "Rust's regex has no look-around"),
        (r"(a)\1", "Rust's regex has no backreferences"),
        (r"(?P<n>a)(?P=n)", "Rust's regex has no backreferences"),
        (r"(?P<n>a)\k<n>", "Rust's regex has no backreferences"),
        (r"Bash\Z", "Rust's regex has no \\Z anchor (write \\z)"),
    ],
)
def test_a_python_only_construct_is_named(pattern, message) -> None:
    """Python compiles each of these silently; Rust drops the matcher group
    with no diagnostic, so the rule has to name the construct itself."""
    assert rust_matcher_error(pattern) == message


def test_the_seam_never_turns_a_look_behind_into_a_named_group() -> None:
    """`(?<tool>...)` is a named group in Rust; `(?<=` and `(?<!` are
    look-behind, which Rust does not have. The two tables that draw this
    line — the named-group rewrite and the unsupported-construct scan — must
    agree on which `(?<` is which, or a look-behind silently becomes a group
    name and passes uncompiled-checked."""
    assert rust_matcher_error(r"(?<=x)y") == "Rust's regex has no look-around"
    assert rust_matcher_error(r"(?<!x)y") == "Rust's regex has no look-around"
    # Confirms the rewrite itself never touches these two spellings.
    assert _to_python_regex(r"(?<=x)y") == r"(?<=x)y"
    assert _to_python_regex(r"(?<!x)y") == r"(?<!x)y"


@pytest.mark.parametrize(
    "pattern",
    [
        r"\(\?=\)",
        r"[(?=]x",
        r"\(?=x\)y",
    ],
)
def test_look_around_spelled_as_literal_text_is_not_reported(pattern) -> None:
    """An escaped `(` or a character class containing `(`, `?` and `=` is
    literal text in both dialects, not the look-around construct."""
    assert rust_matcher_error(pattern) is None


# ── The length cap ─────────────────────────────────────────────────────


def test_rust_matcher_error_caps_the_pattern_it_will_compile() -> None:
    """Past the cap the caller is told nothing rather than "too long":
    neither host imposes a length limit, so length on its own is not a
    defect. An off-by-one on the constant would otherwise be invisible,
    since every other test uses a pattern far past or far under it."""
    at_cap = "(" + "a" * (RUST_MATCHER_MAX_LENGTH - 1)  # unclosed group
    assert len(at_cap) == RUST_MATCHER_MAX_LENGTH

    assert rust_matcher_error(at_cap) is not None  # still checked
    assert rust_matcher_error(at_cap + "a") is None  # one past: left alone
    assert rust_matcher_error("Bash|Write") is None


# ── The `\z` anchor: Rust always has it, Python's `re` only from 3.14 ───


def test_an_unescaped_z_anchor_is_rewritten_and_always_compiles() -> None:
    """Rust's `regex` supports `\\z`; Python's `re` gained it only in 3.14.
    Rewriting it to `\\Z` — semantically the same anchor, supported on every
    Python this project runs on — keeps the check version-independent."""
    assert _to_python_regex("Bash\\z") == "Bash\\Z"
    assert rust_matcher_error("Bash\\z") is None


def test_a_literal_backslash_before_z_is_left_alone() -> None:
    """A *preceding* backslash pairs with the first one as an escaped
    literal backslash, so the `z` that follows is already a literal
    character, not an unescaped anchor — rewriting it would corrupt the
    pattern."""
    assert _to_python_regex("Bash\\\\z") == "Bash\\\\z"
    assert rust_matcher_error("Bash\\\\z") is None


def test_a_z_anchor_inside_a_character_class_is_not_rewritten() -> None:
    """Neither dialect accepts `[\\z]` — Grok 1.0.13 drops the hook and
    Python raises `bad escape` — so the rewrite leaves it alone and the
    compile reports it, instead of a rewrite hiding a real defect."""
    assert _to_python_regex("[\\z]") == "[\\z]"
    assert rust_matcher_error("[\\z]") is not None


def test_the_python_spelling_of_the_anchor_is_named_before_the_rewrite() -> None:
    """The rewrite makes `\\z` and `\\Z` indistinguishable to the compile,
    so the Python-only spelling has to be named first: Rust has no `\\Z`
    (verified: Grok 1.0.13 drops a `Bash\\Z` hook and loads `Bash\\z`). A
    literal backslash before the `Z` is an escaped backslash, not the
    anchor."""
    assert rust_matcher_error("Bash\\Z") is not None
    assert rust_matcher_error("Bash\\\\Z") is None

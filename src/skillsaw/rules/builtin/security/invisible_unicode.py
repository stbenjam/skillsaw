"""Invisible / reordering unicode detection (ASCII smuggling, Trojan Source).

Instructions encoded in Unicode tag characters (U+E0020-U+E007F) render as
nothing in editors and diffs but are read verbatim by LLMs — the "ASCII
smuggling" prompt-injection channel.  Bidirectional control characters
reorder displayed text so reviewers read something different from what the
agent consumes (Trojan Source, CVE-2021-42574).  Zero-width characters hide
payload boundaries inside otherwise innocent prose.  All three families are
flagged wherever agent context is read: content block bodies (including
code fences — payloads hide there too) and frontmatter string values.
"""

import bisect
import re
import unicodedata
from collections import Counter
from itertools import chain
from typing import Any, Dict, FrozenSet, Iterator, List, Optional, Set

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.content_analysis import (
    gather_all_content_blocks,
    FrontmatterField,
)

# Family a: invisible / zero-width characters.
_INVISIBLE_CODEPOINTS = frozenset(
    {
        0x00AD,  # SOFT HYPHEN
        0x180E,  # MONGOLIAN VOWEL SEPARATOR
        0x200B,  # ZERO WIDTH SPACE
        0x200C,  # ZERO WIDTH NON-JOINER
        0x200D,  # ZERO WIDTH JOINER
        0x2060,  # WORD JOINER
        0x2061,  # FUNCTION APPLICATION
        0x2062,  # INVISIBLE TIMES
        0x2063,  # INVISIBLE SEPARATOR
        0x2064,  # INVISIBLE PLUS
        0xFEFF,  # ZERO WIDTH NO-BREAK SPACE (BOM when at file start)
    }
)

# Family b: bidirectional control characters (Trojan Source, CVE-2021-42574).
_BIDI_CODEPOINTS = (
    frozenset({0x061C, 0x200E, 0x200F})  # ALM, LRM, RLM
    | frozenset(range(0x202A, 0x202F))  # LRE, RLE, PDF, LRO, RLO
    | frozenset(range(0x2066, 0x206A))  # LRI, RLI, FSI, PDI
)

# Family c: Unicode tag block — the LLM smuggling channel.  Tag characters
# mirror ASCII (U+E0041 = TAG LATIN CAPITAL LETTER A) so whole instructions
# can be encoded invisibly.  Always flagged.
_TAG_CODEPOINTS = frozenset({0xE0001}) | frozenset(range(0xE0020, 0xE0080))

_ALL_CODEPOINTS = _INVISIBLE_CODEPOINTS | _BIDI_CODEPOINTS | _TAG_CODEPOINTS

# ZWNJ / ZWJ have legitimate uses: emoji ZWJ sequences (family emoji,
# profession emoji) and cursive-script shaping (Arabic, Persian, Indic).
# They are flagged only in a suspicious context — see ``_joiner_suspicious``.
_JOINER_CODEPOINTS = frozenset({0x200C, 0x200D})

# The only legitimate use of tag characters: the three RGI emoji tag
# sequences (England, Scotland, Wales flags) — WAVING BLACK FLAG, a fixed
# region code in tag letters, CANCEL TAG.  Exempted as exact sequences:
# none of them can encode anything but its own region code, so the
# carve-out has zero smuggling capacity.
_RGI_FLAG_SEQUENCES = tuple(
    "\U0001f3f4" + "".join(chr(0xE0000 + ord(ch)) for ch in code) + "\U000e007f"
    for code in ("gbeng", "gbsct", "gbwls")
)


def _rgi_flag_offsets(text: str) -> FrozenSet[int]:
    """Offsets of tag characters that belong to a valid RGI flag emoji."""
    offsets: Set[int] = set()
    for seq in _RGI_FLAG_SEQUENCES:
        start = text.find(seq)
        while start != -1:
            # Skip the flag base (not a tag char); exempt the tag run.
            offsets.update(range(start + 1, start + len(seq)))
            start = text.find(seq, start + len(seq))
    return frozenset(offsets)


def _iter_strings(value: Any, _seen: Optional[Set[int]] = None) -> Iterator[str]:
    """Yield every string embedded in a frontmatter value.

    Nested lists and mappings are walked (mapping keys included): a payload
    in ``allowed-tools: [Ba<ZWSP>sh]`` never surfaces through ``str(value)``
    because ``repr`` backslash-escapes format characters.

    Containers already visited are skipped by ``id`` so self-referential
    structures built from YAML anchor/alias cycles (``metadata: &m\\n
    nested: *m`` — legal YAML that PyYAML constructs as a dict containing
    itself) terminate instead of raising ``RecursionError``.
    """
    if isinstance(value, str):
        yield value
        return
    if not isinstance(value, (dict, list, tuple)):
        return
    if _seen is None:
        _seen = set()
    if id(value) in _seen:
        return
    _seen.add(id(value))
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str):
                yield key
            yield from _iter_strings(item, _seen)
    else:
        for item in value:
            yield from _iter_strings(item, _seen)


def _joiner_suspicious(text: str, index: int) -> bool:
    """True when the ZWNJ/ZWJ at ``text[index]`` looks like smuggling.

    Legitimate joiners sit between emoji or cursive-script characters (all
    non-ASCII).  A joiner adjacent to an ASCII character was inserted into
    plain text to split tokens invisibly, and a joiner adjacent to another
    listed invisible character is part of a stacked-invisible payload.
    """
    for neighbor_index in (index - 1, index + 1):
        if 0 <= neighbor_index < len(text):
            neighbor = ord(text[neighbor_index])
            if neighbor < 0x80 or neighbor in _ALL_CODEPOINTS:
                return True
    return False


# A smuggled sentence can span dozens of distinct tag codepoints; cap the
# enumeration so the message stays readable.
_MAX_CODEPOINTS_LISTED = 8


def _visible(text: str) -> str:
    """Replace listed invisible characters with visible ``<U+XXXX>`` escapes.

    Violation messages are read by agents too — echoing a poisoned
    frontmatter key verbatim would re-smuggle the payload through the
    lint report itself.  Truncated so a long smuggled key cannot bloat
    the message.
    """
    escaped = "".join(f"<U+{ord(ch):04X}>" if ord(ch) in _ALL_CODEPOINTS else ch for ch in text)
    if len(escaped) > 60:
        return escaped[:60] + "…"
    return escaped


def _codepoint_summary(counts: Counter) -> str:
    """Render per-codepoint hit counts, e.g. ``3x U+200B (ZERO WIDTH SPACE)``."""
    parts = []
    for codepoint in sorted(counts)[:_MAX_CODEPOINTS_LISTED]:
        try:
            name = unicodedata.name(chr(codepoint))
        except ValueError:
            name = "invisible character"
        parts.append(f"{counts[codepoint]}x U+{codepoint:04X} ({name})")
    overflow = len(counts) - _MAX_CODEPOINTS_LISTED
    if overflow > 0:
        parts.append(f"and {overflow} more invisible codepoint(s)")
    return ", ".join(parts)


class SecurityInvisibleUnicodeRule(Rule):
    """Detect invisible and reordering unicode in agent context"""

    formats = None
    repo_types = None
    since = "0.17.0"

    config_schema = {
        "allow-bidi-controls": {
            "type": "bool",
            "default": False,
            "description": (
                "Suppress bidirectional control characters (U+061C, "
                "U+200E/U+200F, U+202A-U+202E, U+2066-U+2069) entirely, "
                "disabling Trojan Source detection — prefer exempting the "
                "specific implicit-mark codepoints via allowed-codepoints"
            ),
        },
        "allowed-codepoints": {
            "type": "list",
            "default": [],
            "description": (
                'Codepoints to exempt from detection, as "U+XXXX" / "0xXXXX" '
                "strings or bare integers (unquoted YAML 0x200B works), "
                'e.g. ["U+00AD"] for content that uses soft hyphens'
            ),
        },
    }

    @property
    def rule_id(self) -> str:
        return "security-invisible-unicode"

    @property
    def description(self) -> str:
        return (
            "Detect invisible or reordering unicode characters "
            "(ASCII smuggling, Trojan Source) in agent context"
        )

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def _allowed_codepoints(self) -> Set[int]:
        raw = self.config.get("allowed-codepoints", [])
        if not isinstance(raw, list):
            return set()
        allowed = set()
        for item in raw:
            if isinstance(item, bool):
                continue  # YAML true/false is not a codepoint
            if isinstance(item, int):
                # Unquoted YAML scalars arrive as ints — ``0x200B`` is
                # already 8203 by the time PyYAML delivers it, so the value
                # IS the codepoint.  Feeding str(8203) through the hex
                # parser below would exempt U+8203 instead of U+200B.
                if 0 <= item <= 0x10FFFF:
                    allowed.add(item)
                continue
            text = str(item).strip().upper()
            if text.startswith("U+"):
                text = text[2:]
            elif text.startswith("0X"):
                text = text[2:]
            try:
                allowed.add(int(text, 16))
            except ValueError:
                continue
        return allowed

    def _build_pattern(self) -> Optional[re.Pattern]:
        """Compile ONE character class covering every flaggable codepoint."""
        codepoints = set(_ALL_CODEPOINTS) - self._allowed_codepoints()
        if self.config.get("allow-bidi-controls", False):
            codepoints -= _BIDI_CODEPOINTS
        if not codepoints:
            return None
        char_class = "".join(re.escape(chr(c)) for c in sorted(codepoints))
        return re.compile(f"[{char_class}]")

    def _hits_by_line(
        self, text: str, pattern: re.Pattern, *, skip_leading_bom: bool
    ) -> Dict[int, Counter]:
        """Map 1-based line number -> Counter of flagged codepoints.

        One whole-text ``finditer`` pass is the gate — clean text costs a
        single scan and no per-line work.  Line offsets are computed only
        when there is at least one surviving hit.
        """
        hit_offsets = []
        flag_offsets: Optional[FrozenSet[int]] = None  # computed on first tag hit
        for match in pattern.finditer(text):
            index = match.start()
            codepoint = ord(text[index])
            if skip_leading_bom and index == 0 and codepoint == 0xFEFF:
                continue  # byte-order mark, not a payload
            if codepoint in _JOINER_CODEPOINTS and not _joiner_suspicious(text, index):
                continue  # emoji sequence or cursive-script shaping
            if codepoint in _TAG_CODEPOINTS:
                if flag_offsets is None:
                    flag_offsets = _rgi_flag_offsets(text)
                if index in flag_offsets:
                    continue  # England / Scotland / Wales flag emoji
            hit_offsets.append(index)
        if not hit_offsets:
            return {}
        line_starts = [0]
        newline = text.find("\n")
        while newline != -1:
            line_starts.append(newline + 1)
            newline = text.find("\n", newline + 1)
        by_line: Dict[int, Counter] = {}
        for offset in hit_offsets:
            line_num = bisect.bisect_right(line_starts, offset)
            by_line.setdefault(line_num, Counter())[ord(text[offset])] += 1
        return by_line

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        pattern = self._build_pattern()
        if pattern is None:
            return []
        violations = []
        for cf in gather_all_content_blocks(context):
            body = cf.read_body(strip_code_blocks=False)
            if not body:
                continue
            # U+FEFF at offset 0 is a BOM only when the body starts at the
            # top of the file; a frontmattered body starts mid-file, where
            # a leading U+FEFF is as suspicious as any other.
            skip_bom = cf.file_line(1) == 1
            by_line = self._hits_by_line(body, pattern, skip_leading_bom=skip_bom)
            for line_num in sorted(by_line):
                violations.append(
                    self.violation(
                        f"Invisible unicode: {_codepoint_summary(by_line[line_num])}"
                        " — invisible to reviewers, visible to agents",
                        block=cf,
                        line=line_num,
                    )
                )
        for fld in context.lint_tree.find(FrontmatterField):
            # Walk every string in the value (nested lists/maps, keys
            # included) plus the field name itself — str() of a container
            # repr-escapes format characters, hiding the payload.  The name
            # goes through _iter_strings too: YAML legally produces
            # non-string keys (``2024:`` -> int, ``2024-01-01:`` -> date,
            # ``on:`` -> bool under YAML 1.1) which must not reach
            # ``finditer`` — non-string scalars cannot carry invisible
            # characters, so skipping them loses nothing.
            total: Counter = Counter()
            for text in chain(_iter_strings(fld.name), _iter_strings(fld.value)):
                if not text:
                    continue
                by_line = self._hits_by_line(text, pattern, skip_leading_bom=False)
                for counts in by_line.values():
                    total.update(counts)
            if not total:
                continue
            name_text = fld.name if isinstance(fld.name, str) else str(fld.name)
            violations.append(
                self.violation(
                    f"Invisible unicode in frontmatter field '{_visible(name_text)}': "
                    f"{_codepoint_summary(total)}"
                    " — invisible to reviewers, visible to agents",
                    file_path=fld.path,
                    line=fld.field_line,
                )
            )
        return violations

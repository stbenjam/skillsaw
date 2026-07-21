"""Security encoded payload rule.

Long high-entropy base64/hex blobs in agent context are payload-smuggling
vehicles ("decode and execute this").  ``hooks-dangerous`` catches the
``base64 -d`` decode step in hook commands; this rule catches the payload
itself sitting in content.
"""

import math
import re
from typing import Iterator, List, Tuple

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.content_analysis import (
    gather_all_content_blocks,
    FrontmatterField,
)

# Minimum run length before a blob is even considered.  120 chars of base64
# decodes to 90 bytes — enough for a meaningful shell payload, while staying
# comfortably above commit SHAs (40/64 hex) and SRI hashes (88 base64).
_DEFAULT_MIN_LENGTH = 120

# Entropy gates in bits/char over the matched run.  Random base64 measures
# ~5.7-6.0 and random hex ~3.8-4.0 (a 16-symbol alphabet caps at 4.0), while
# repeated filler ("AAAA…") measures near 0 and English-ish text stays well
# below both gates.
_DEFAULT_BASE64_ENTROPY = 4.5
_DEFAULT_HEX_ENTROPY = 3.4

# Runs whose min-length is configured below this are clamped: tiny minimums
# would flag ordinary words and make the regex gate useless.
_MIN_LENGTH_FLOOR = 16

_HEX_CHARS = frozenset("0123456789abcdefABCDEF")

# Line context immediately before a run that marks it as a legitimate
# integrity pin: SRI attributes (integrity="sha384-…") and container image
# digests (image@sha256:…).
_INTEGRITY_MARKERS = ("integrity=", "sha256-", "sha384-", "sha512-", "sha256:")
_INTEGRITY_WINDOW = 20

# With "-" in the run alphabet, a "sha384-…" pin is swallowed into the run
# itself instead of appearing in the preceding context window — recognize
# the marker at the run head as well.
_INTEGRITY_PREFIXES = ("sha256-", "sha384-", "sha512-")

# Embedded logos/badges as data-URI images are legitimate; the scheme prefix
# sits a bit further back on the line ("data:image/png;base64,<run>").
_DATA_URI_MARKER = "data:image/"
_DATA_URI_WINDOW = 80


def _shannon_entropy(value: str) -> float:
    """Shannon entropy of *value* in bits per character.

    Deliberate duplication of the private helper in
    ``content/embedded_secrets.py`` — rule modules are independently
    auto-discovered and must not import each other's private helpers.
    """
    if not value:
        return 0.0
    length = len(value)
    counts = {}
    for ch in value:
        counts[ch] = counts.get(ch, 0) + 1
    return -sum((n / length) * math.log2(n / length) for n in counts.values())


def _is_exempt(line: str, start: int, run: str) -> bool:
    """True when the run starting at *start* on *line* is a legitimate blob."""
    if run.lower().startswith(_INTEGRITY_PREFIXES):
        return True
    integrity_context = line[max(0, start - _INTEGRITY_WINDOW) : start].lower()
    if any(marker in integrity_context for marker in _INTEGRITY_MARKERS):
        return True
    data_uri_context = line[max(0, start - _DATA_URI_WINDOW) : start].lower()
    return _DATA_URI_MARKER in data_uri_context


class SecurityEncodedPayloadRule(Rule):
    """Detect long high-entropy base64/hex blobs in agent context"""

    repo_types = None
    formats = None
    since = "0.17.0"

    config_schema = {
        "min-length": {
            "type": "int",
            "default": _DEFAULT_MIN_LENGTH,
            "description": (
                "Minimum length of a base64/hex character run before it is "
                f"considered a payload candidate (floor: {_MIN_LENGTH_FLOOR})"
            ),
        },
        "entropy-threshold": {
            "type": "float",
            "default": _DEFAULT_BASE64_ENTROPY,
            "description": (
                "Minimum Shannon entropy (bits/char) a base64 run must reach "
                "to be reported; random base64 measures ~5.7-6.0"
            ),
        },
        "hex-entropy-threshold": {
            "type": "float",
            "default": _DEFAULT_HEX_ENTROPY,
            "description": (
                "Minimum Shannon entropy (bits/char) a hex run must reach to "
                "be reported; the 16-symbol alphabet caps at 4.0"
            ),
        },
    }

    @property
    def rule_id(self) -> str:
        return "security-encoded-payload"

    @property
    def description(self) -> str:
        return "Detect long high-entropy base64/hex blobs that can smuggle encoded payloads"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def _int_config(self, key: str, default: int) -> int:
        try:
            return int(self.config.get(key, default))
        except (TypeError, ValueError):
            return default

    def _float_config(self, key: str, default: float) -> float:
        try:
            return float(self.config.get(key, default))
        except (TypeError, ValueError):
            return default

    def _scan_text(
        self,
        text: str,
        patterns: Tuple[re.Pattern, ...],
        min_length: int,
        base64_threshold: float,
        hex_threshold: float,
    ) -> Iterator[Tuple[int, str, str, float]]:
        """Yield ``(line_num, kind, run, entropy)`` — at most one per line.

        ``patterns_matching_anywhere()`` cannot prefilter here: its C-speed
        substring stage needs a required literal extracted from the pattern,
        and a pure character-class run has none.  The cheap gate is instead a
        compiled whole-text search per alphabet; per-line work only happens
        for alphabets whose gate hits.
        """
        live = [p for p in patterns if p.search(text) is not None]
        if not live:
            return
        # Split on "\n" only — NOT splitlines(), which also splits on
        # U+2028/U+2029/NEL/VT/FF and would drift the reported line number
        # away from the \n-counted file line (an attacker could plant a
        # U+2028 to point the violation at an innocent line).  read_text()
        # already collapses CRLF to \n.
        for line_num, line in enumerate(text.split("\n"), 1):
            if len(line) < min_length:
                continue  # a shorter line cannot contain a qualifying run
            # Merge both alphabets' matches in line order, longest first at
            # equal starts so the reported length is the full run. Dedupe
            # only identical spans — same-start runs of different lengths
            # are distinct candidates, and each must be evaluated: whichever
            # ordering went first, gating the other on its start would let
            # a mixed-entropy prefix mask a qualifying run (or vice versa).
            matches = sorted(
                (m for p in live for m in p.finditer(line)),
                key=lambda m: (m.start(), -m.end()),
            )
            seen_spans = set()
            for m in matches:
                if m.span() in seen_spans:
                    continue
                seen_spans.add(m.span())
                run = m.group(0)
                # The hex alphabet is a subset of the base64 alphabet, so a
                # single pattern matches both; classify by inspecting the
                # matched characters.
                if all(ch in _HEX_CHARS for ch in run):
                    kind, threshold = "hex", hex_threshold
                else:
                    kind, threshold = "base64", base64_threshold
                # A qualifying run of real encoded data essentially always
                # contains a digit (P(no digit in 120 random base64 chars) =
                # (52/64)^120 ~= 1.5e-11; for hex it is (6/16)^120).  A
                # digit-free run is concatenated natural text — a long
                # camelCase identifier or a deep /src/main/java/... path —
                # which can crest the base64 gate (measured 4.54 bits/char
                # on a 124-char identifier vs the 4.5 threshold), and a
                # digit-free mixed-case a-fA-F run (12 symbols, entropy cap
                # log2(12) ~= 3.58) can crest the 3.4 hex gate.
                if not any(ch.isdigit() for ch in run):
                    continue
                entropy = _shannon_entropy(run)
                if entropy < threshold:
                    continue
                if _is_exempt(line, m.start(), run):
                    continue
                yield line_num, kind, run, entropy
                break  # one violation per line max

    @staticmethod
    def _describe(kind: str, run: str, entropy: float) -> str:
        # Never echo the full blob — a 20-char head is enough to locate it.
        return (
            f"{kind} run of {len(run)} chars " f'(entropy {entropy:.1f} bits/char): "{run[:20]}…"'
        )

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        min_length = max(self._int_config("min-length", _DEFAULT_MIN_LENGTH), _MIN_LENGTH_FLOOR)
        base64_threshold = self._float_config("entropy-threshold", _DEFAULT_BASE64_ENTROPY)
        hex_threshold = self._float_config("hex-entropy-threshold", _DEFAULT_HEX_ENTROPY)
        # One pattern per encoding alphabet: standard base64 ("+"/"/") and
        # base64url (RFC 4648 §5: "-"/"_", used by JWTs and web tokens).
        # Deliberately NOT a single union class — no decoder accepts a mix
        # of "/" and "-", and the union run swallows long URL paths
        # (".../test-platform-results/pr-logs/pull/30393/...") that crest
        # the entropy gate. Alphabet-pure runs inside such a path are still
        # caught: the other alphabet's separators bound them. Hex runs are
        # a subset of both and split out during classification.
        patterns = (
            re.compile(r"[A-Za-z0-9+/]{%d,}={0,2}" % min_length),
            re.compile(r"[A-Za-z0-9_-]{%d,}={0,2}" % min_length),
        )

        violations = []
        for cf in gather_all_content_blocks(context):
            # Payloads hide in fences at least as often as in prose — scan
            # the full body including code blocks.
            body = cf.read_body(strip_code_blocks=False)
            if not body:
                continue
            for line_num, kind, run, entropy in self._scan_text(
                body, patterns, min_length, base64_threshold, hex_threshold
            ):
                violations.append(
                    self.violation(
                        f"Possible encoded payload: {self._describe(kind, run, entropy)}",
                        block=cf,
                        line=line_num,
                    )
                )
        for fld in context.lint_tree.find(FrontmatterField):
            text = str(fld.value) if fld.value is not None else ""
            if len(text) < min_length:
                continue
            for _line_num, kind, run, entropy in self._scan_text(
                text, patterns, min_length, base64_threshold, hex_threshold
            ):
                violations.append(
                    self.violation(
                        f"Possible encoded payload in frontmatter field "
                        f"'{fld.name}': {self._describe(kind, run, entropy)}",
                        file_path=fld.path,
                        line=fld.field_line,
                    )
                )
                break  # one violation per field
        return violations

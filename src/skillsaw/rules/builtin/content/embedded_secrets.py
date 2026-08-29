"""Content embedded secrets rule"""

import math
import re
from typing import List, Optional, Tuple

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.content_analysis import (
    gather_all_content_blocks,
    patterns_matching_anywhere,
    FrontmatterField,
)
from skillsaw.rules.builtin.secret_detection import (
    KNOWN_SECRET_EXAMPLE_VALUES,
    STRUCTURED_SECRET_PATTERNS,
    is_secret_placeholder,
    placeholder_markers,
)

# Default minimum Shannon entropy (bits/char) a generic ``key = "value"``
# candidate must reach before it is reported.  Random secrets (base64, hex,
# mixed-character passwords) comfortably exceed this; English-ish placeholder
# strings mostly do not.  Structured token formats (AKIA…, ghp_…, private-key
# blocks) are high-confidence and are never entropy-gated.
_DEFAULT_ENTROPY_THRESHOLD = 3.5

# Shannon entropy per character of an n-char string is capped at log2(n),
# so short values can never reach a threshold tuned for long ones (a fully
# random 10-char password measures at most 3.32 bits/char).  Values shorter
# than 16 chars are normalized to this 16-char reference (log2(16) = 4.0
# bits) so the threshold discriminates uniformly across lengths.
_REFERENCE_MAX_BITS = 4.0

# Audited fragments of the canonical AWS documentation ID.  Comparing the
# fixed prefix and remainder keeps the exception exact without adding another
# contiguous access-key-shaped value that repository push protection rejects.
_AWS_DOCUMENTATION_ACCESS_KEY_ID_PARTS = ("AKIAIOSF", "ODNN7EXAMPLE")
_RSA_PRIVATE_KEY_HEADER = "-----BEGIN RSA PRIVATE KEY-----"

# Exact literals audited from public documentation corpora, compared
# case-insensitively after trimming surrounding whitespace. These are values,
# not substring markers: a candidate containing extra text remains reportable.
# The RSA header has an additional context check below so a PEM block carrying
# key material is never exempted.
_KNOWN_EXAMPLE_VALUES = KNOWN_SECRET_EXAMPLE_VALUES | frozenset(
    {
        "sk_live_abc123xyz789",
        "sk_live_abc123def456",
        "django-insecure-...",
        _RSA_PRIVATE_KEY_HEADER,
    }
)
_KNOWN_EXAMPLE_VALUE_CASEFOLDS = frozenset(value.casefold() for value in _KNOWN_EXAMPLE_VALUES)
_PEM_BASE64_LINE = re.compile(r"[A-Za-z0-9+/]+={0,2}")
_PEM_KEY_MATERIAL_MIN_CHARS = 32
_PEM_END_MARKER = "-----END RSA PRIVATE KEY-----"
_PEM_METADATA_FIELD = re.compile(
    r"(?:Proc-Type\s*:\s*4\s*,\s*ENCRYPTED|"
    r"DEK-Info\s*:\s*[A-Za-z0-9-]+\s*,\s*[0-9A-Fa-f]{16,32}"
    r"(?![0-9A-Fa-f]))",
    re.IGNORECASE,
)
_PEM_SERIALIZED_LINE_BREAK = re.compile(r"(?:\\+r)?\\+n")
_PEM_LOOKAHEAD_PHYSICAL_LINES = 40
_PEM_LOOKAHEAD_CHARS_PER_LINE = 4096
# Punctuation that can decorate a complete logical line in Markdown, YAML,
# JSON, or shell examples. Base64 characters (+, /, =) are deliberately not
# stripped. Payload recognition below still requires the entire undecorated
# logical line to be base64-shaped.
_PEM_LINE_DECORATION = " \t\r\"'`,;:.!?()[]{}<>|~*_-#\\"
# Alphanumeric characters and these two punctuation marks can extend the
# header into a larger token. Every other character is a syntax delimiter.
_RSA_HEADER_TOKEN_EXTENDERS = frozenset("-_")


def _shannon_entropy(value: str) -> float:
    """Shannon entropy of *value* in bits per character."""
    if not value:
        return 0.0
    length = len(value)
    counts = {}
    for ch in value:
        counts[ch] = counts.get(ch, 0) + 1
    return -sum((n / length) * math.log2(n / length) for n in counts.values())


def _length_adjusted_entropy(value: str) -> float:
    """Shannon entropy normalized for short samples.

    For values shorter than 16 characters the raw per-char entropy is scaled
    up by ``4.0 / log2(len)`` — the ratio between the 16-char reference
    ceiling and the value's own ceiling — so a fully random 8-char password
    (raw max 3.0 bits/char) is comparable against the same threshold as a
    32-char one.  Longer values are returned unscaled.
    """
    raw = _shannon_entropy(value)
    if len(value) < 2:
        return raw
    max_bits = math.log2(len(value))
    if max_bits >= _REFERENCE_MAX_BITS:
        return raw
    return raw * (_REFERENCE_MAX_BITS / max_bits)


def _is_known_example_value(value: str) -> bool:
    """Whether normalized *value* matches one audited documentation literal."""
    normalized = value.strip().casefold()
    if normalized in _KNOWN_EXAMPLE_VALUE_CASEFOLDS:
        return True
    prefix, remainder = _AWS_DOCUMENTATION_ACCESS_KEY_ID_PARTS
    prefix = prefix.casefold()
    return normalized.startswith(prefix) and normalized[len(prefix) :] == remainder.casefold()


def _pem_payload_chars(candidate: str) -> Optional[int]:
    """Count a credible base64 payload line after normalizing whitespace."""
    groups = candidate.split()
    if not groups or any(_PEM_BASE64_LINE.fullmatch(group) is None for group in groups):
        return None
    compact = "".join(groups)
    if _PEM_BASE64_LINE.fullmatch(compact) is None:
        return None
    if len(groups) > 1:
        group_width = len(groups[0])
        regularly_grouped = (
            all(len(group) == group_width for group in groups[:-1])
            and len(groups[-1]) <= group_width
        )
        # Unencrypted PKCS#1 RSA DER begins with ``MI`` in base64. Otherwise,
        # require regular grouping so variable-length prose words cannot be
        # concatenated into an apparent payload.
        if not compact.startswith("MI") and not regularly_grouped:
            return None
    return len(compact.rstrip("="))


def _pem_context_segments(candidate: str) -> Tuple[List[Optional[int]], bool]:
    """Classify one bounded physical PEM-context line.

    Returns payload character counts for base64-shaped logical lines, ``None``
    for non-payload logical lines, and whether the RSA end marker was reached.
    Empty lines and exact encryption metadata are neutral. This lets callers
    continue a bounded search past Markdown labels without letting prose
    contribute base64-looking words to the payload aggregate.
    """
    bounded = candidate[:_PEM_LOOKAHEAD_CHARS_PER_LINE]
    marker_index = bounded.find(_PEM_END_MARKER)
    reached_end_marker = marker_index >= 0
    if reached_end_marker:
        bounded = bounded[:marker_index]

    segments: List[Optional[int]] = []
    for logical_line in _PEM_SERIALIZED_LINE_BREAK.split(bounded):
        without_metadata = _PEM_METADATA_FIELD.sub("", logical_line)
        undecorated = without_metadata.strip(_PEM_LINE_DECORATION)
        if not undecorated:
            continue
        payload_chars = _pem_payload_chars(undecorated)
        if payload_chars is None:
            segments.append(None)
            continue
        segments.append(payload_chars)
    return segments, reached_end_marker


def _pem_material_progress(material_chars: int, candidate: str) -> Tuple[int, bool, bool]:
    """Advance one bounded candidate, resetting at non-payload segments."""
    segments, reached_end_marker = _pem_context_segments(candidate)
    for segment_chars in segments:
        if segment_chars is None:
            material_chars = 0
            continue
        material_chars += segment_chars
        if material_chars >= _PEM_KEY_MATERIAL_MIN_CHARS:
            return material_chars, reached_end_marker, True
    return material_chars, reached_end_marker, False


def _is_rsa_header_delimiter(character: str) -> bool:
    """Whether *character* delimits rather than extends the header token."""
    return not character or (
        not character.isalnum() and character not in _RSA_HEADER_TOKEN_EXTENDERS
    )


class ContentEmbeddedSecretsRule(Rule):
    """Detect potential secrets embedded in instruction files"""

    formats = None
    since = "0.7.0"

    config_schema = {
        "entropy-threshold": {
            "type": "float",
            "default": _DEFAULT_ENTROPY_THRESHOLD,
            "description": (
                'Minimum Shannon entropy (bits/char) a generic key = "value" '
                "match must reach to be reported; structured tokens (AKIA…, "
                "ghp_…, private keys) remain reportable except for exact "
                "audited documentation literals"
            ),
        },
        "additional-placeholders": {
            "type": "list",
            "default": [],
            "description": (
                "Extra case-insensitive substrings that mark a generic "
                "credential value as a placeholder (suppressing the violation)"
            ),
        },
    }

    # Each entry is (compiled_pattern, description, is_generic). Structured
    # token formats are high-confidence unless an exact audited documentation
    # literal applies. Generic assignment patterns capture the candidate value
    # in group 1 and are gated by the placeholder allowlist and entropy threshold.
    _PATTERNS = [(pattern, desc, False) for pattern, desc in STRUCTURED_SECRET_PATTERNS] + [
        (re.compile(p), desc, generic)
        for p, desc, generic in [
            # Generic patterns — value captured for placeholder/entropy gating
            (r"(?i)\bpassword\s*[=:]\s*['\"]([^'\"]{8,})['\"]", "Hardcoded password", True),
            (r"(?i)\bapi[_-]?key\s*[=:]\s*['\"]([^'\"]{16,})['\"]", "Hardcoded API key", True),
            (
                r"(?i)\bsecret[_-]?key\s*[=:]\s*['\"]([^'\"]{16,})['\"]",
                "Hardcoded secret key",
                True,
            ),
            (
                r"(?i)\baccess[_-]?token\s*[=:]\s*['\"]([^'\"]{16,})['\"]",
                "Hardcoded access token",
                True,
            ),
        ]
    ]

    @property
    def rule_id(self) -> str:
        return "content-embedded-secrets"

    @property
    def description(self) -> str:
        return "Detect potential API keys, tokens, and passwords in instruction files"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def _entropy_threshold(self) -> float:
        try:
            return float(self.config.get("entropy-threshold", _DEFAULT_ENTROPY_THRESHOLD))
        except (TypeError, ValueError):
            return _DEFAULT_ENTROPY_THRESHOLD

    def _placeholder_markers(self) -> Tuple[str, ...]:
        return placeholder_markers(self.config.get("additional-placeholders", []))

    @staticmethod
    def _is_placeholder(value: str, markers: Tuple[str, ...]) -> bool:
        """True when *value* is clearly a placeholder, not a real secret."""
        if _is_known_example_value(value):
            return True
        return is_secret_placeholder(value, markers)

    @staticmethod
    def _pem_key_material_follows(lines: List[str], line_index: int, match: re.Match) -> bool:
        """Whether an RSA header introduces key material instead of teaching text."""
        remainder = lines[line_index][match.end() : match.end() + _PEM_LOOKAHEAD_CHARS_PER_LINE]
        material_chars, reached_end_marker, detected = _pem_material_progress(0, remainder)
        if detected:
            return True
        if reached_end_marker:
            return False

        # Forty physical lines accommodate traditional encryption metadata, a
        # blank separator, and the 32 one-column base64 characters needed to
        # reach the evidence threshold. The fixed limit still bounds blank or
        # long input for every header in adversary-controlled text.
        lookahead_end = min(len(lines), line_index + 1 + _PEM_LOOKAHEAD_PHYSICAL_LINES)
        for following_index in range(line_index + 1, lookahead_end):
            candidate = lines[following_index][:_PEM_LOOKAHEAD_CHARS_PER_LINE]
            material_chars, reached_end_marker, detected = _pem_material_progress(
                material_chars, candidate
            )
            if detected:
                return True
            if reached_end_marker:
                return False
        return False

    @classmethod
    def _structured_match_reportable(
        cls, lines: List[str], line_index: int, match: re.Match
    ) -> bool:
        """Keep structured-token exceptions exact and PEM-material aware."""
        value = match.group(0)
        if not _is_known_example_value(value):
            return True

        line = lines[line_index]
        previous_char = line[match.start() - 1 : match.start()]
        next_char = line[match.end() : match.end() + 1]
        if value == _RSA_PRIVATE_KEY_HEADER:
            if not _is_rsa_header_delimiter(previous_char) or not _is_rsa_header_delimiter(
                next_char
            ):
                # The header is embedded in a larger token, not standalone.
                return True
            return cls._pem_key_material_follows(lines, line_index, match)

        # AWS access-key IDs contain only uppercase letters and digits. Syntax
        # such as '=' or quotes delimits the known documentation value, while
        # another format-valid character makes it a longer reportable token.
        if next_char and next_char in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
            return True
        return False

    def _generic_match_reportable(
        self, value: Optional[str], threshold: float, markers: Tuple[str, ...]
    ) -> bool:
        """Gate a generic ``key = "value"`` candidate: skip obvious
        placeholders and low-entropy (English-ish) strings."""
        if value is None:
            return False
        if self._is_placeholder(value, markers):
            return False
        return _length_adjusted_entropy(value) >= threshold

    def _scan_text(self, text: str, threshold: float, markers: Tuple[str, ...]):
        """Yield ``(line_num, desc)`` for at most one violation per line."""
        active = patterns_matching_anywhere(text, self._PATTERNS)
        if not active:
            return
        # Split on "\n" only, not str.splitlines(), which also breaks on
        # U+2028/U+2029/NEL/VT/FF — block file-line translation counts "\n",
        # so those extra splits would misattribute a match to the wrong line
        # (a payload could plant a U+2028 to point the finding elsewhere).
        # read_body() has already normalized CRLF.
        lines = text.split("\n")
        for line_index, line in enumerate(lines):
            line_num = line_index + 1
            for pattern, desc, is_generic in active:
                if not is_generic:
                    if any(
                        self._structured_match_reportable(lines, line_index, match)
                        for match in pattern.finditer(line)
                    ):
                        yield line_num, desc
                        break
                    continue
                if any(
                    self._generic_match_reportable(m.group(1), threshold, markers)
                    for m in pattern.finditer(line)
                ):
                    yield line_num, desc
                    break

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        threshold = self._entropy_threshold()
        markers = self._placeholder_markers()
        violations = []
        for cf in gather_all_content_blocks(context):
            body = cf.read_body(strip_code_blocks=False)
            if not body:
                continue
            for line_num, desc in self._scan_text(body, threshold, markers):
                violations.append(
                    self.violation(
                        f"Potential secret detected: {desc}",
                        block=cf,
                        line=line_num,
                    )
                )
        for fld in context.lint_tree.find(FrontmatterField):
            text = str(fld.value) if fld.value is not None else ""
            if not text:
                continue
            for _line_num, desc in self._scan_text(text, threshold, markers):
                violations.append(
                    self.violation(
                        f"Potential secret detected in frontmatter " f"field '{fld.name}': {desc}",
                        file_path=fld.path,
                        line=fld.field_line,
                    )
                )
                break
        return violations

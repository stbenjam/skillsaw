"""Content embedded secrets rule"""

import base64
import binascii
import math
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from skillsaw.markdown_doc import MarkdownDoc
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
# Every PEM private-key header the structured detector matches. A header is
# documentation until key material follows it: security skills list the
# headers they scan for, and a header line alone leaks nothing.
_PEM_PRIVATE_KEY_HEADER_RE = re.compile(r"\A-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----\Z")
# The jwt.io example token (HS256, secret "your-256-bit-secret"), reproduced
# verbatim across API documentation.
_JWT_IO_EXAMPLE_TOKEN = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ."
    "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
)
# A run of one repeated character eight or more long. Random token material
# never contains one; `ghp_xxxxxxxx…` and `AIzaSyXXXX…` placeholders always do.
_REPEATED_CHARACTER_RUN_RE = re.compile(r"(.)\1{7,}")

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
        _JWT_IO_EXAMPLE_TOKEN,
    }
)
_KNOWN_EXAMPLE_VALUE_CASEFOLDS = frozenset(value.casefold() for value in _KNOWN_EXAMPLE_VALUES)
_PEM_BASE64_LINE = re.compile(r"[A-Za-z0-9+/]+={0,2}")
_PEM_KEY_MATERIAL_MIN_CHARS = 32
_PEM_ENCRYPTED_MATERIAL_MIN_CHARS = 64
_PEM_ENCRYPTED_MATERIAL_MIN_ENTROPY = 4.5
_PEM_END_MARKER = "-----END RSA PRIVATE KEY-----"
_PEM_METADATA_FIELD = re.compile(
    r"(?:Proc-Type\s*:\s*4\s*,\s*ENCRYPTED|"
    r"DEK-Info\s*:\s*[A-Za-z0-9-]+\s*,\s*[0-9A-Fa-f]{16,32}"
    r"(?![0-9A-Fa-f]))",
    re.IGNORECASE,
)
_PEM_SERIALIZED_LINE_BREAK = re.compile(r"(?:\\+r)?\\+n|(?:\\+u000[dD])?\\+u000[aA]")
_PEM_SERIALIZED_SOLIDUS = re.compile(r"\\+(?:/|u002[fF])")
_PEM_SERIALIZED_HORIZONTAL_SPACE = re.compile(r"\\+(?:t|u0009|u0020)")
_PEM_LOOKAHEAD_PHYSICAL_LINES = 72
_PEM_LOOKAHEAD_CHARS_PER_LINE = 4096
_PEM_SCAN_MAX_CHARS_PER_BLOB = 1024 * 1024
_PEM_SCAN_MIN_CANDIDATE_COST = 64
# Punctuation that can decorate a complete logical line in Markdown, YAML,
# JSON, or shell examples. Base64 characters (+, /, =) are deliberately not
# stripped. Payload recognition below still requires the entire undecorated
# logical line to be base64-shaped.
_PEM_LINE_DECORATION = " \t\r\"'`,;:.!?()[]{}<>|~*_-#\\"
# Alphanumeric characters and these two punctuation marks can extend the
# header into a larger token. Every other character is a syntax delimiter.
_RSA_HEADER_TOKEN_EXTENDERS = frozenset("-_")


@dataclass
class _PemMaterialState:
    """Bounded evidence accumulated after one standalone RSA header."""

    material: str = ""
    encrypted: bool = False


@dataclass
class _PemScanBudget:
    """Cap aggregate PEM lookahead work across one scanned content blob."""

    remaining_chars: int

    def claim(self, candidate: str) -> bool:
        # Charge a small fixed floor so many empty/short lines cannot evade a
        # character-only budget. Exhaustion reports the header (fails secure).
        cost = max(_PEM_SCAN_MIN_CANDIDATE_COST, len(candidate))
        if cost > self.remaining_chars:
            self.remaining_chars = 0
            return False
        self.remaining_chars -= cost
        return True


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


def _pem_payload_text(candidate: str) -> Optional[str]:
    """Normalize a wholly base64-shaped payload line's whitespace."""
    groups = candidate.split()
    if not groups or any(_PEM_BASE64_LINE.fullmatch(group) is None for group in groups):
        return None
    compact = "".join(groups)
    if _PEM_BASE64_LINE.fullmatch(compact) is None:
        return None
    return compact


def _decoded_base64_prefix(material: str) -> Optional[bytes]:
    """Decode every complete base64 quantum available in *material*."""
    remainder = len(material) % 4
    if len(material) < 4:
        if len(material) == 1:
            return b"" if material == "M" else None
        encoded = material + "=" * (4 - len(material))
    elif remainder == 1:
        encoded = material[:-1]
    else:
        encoded = material + "=" * ((4 - remainder) % 4)
    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return None


def _rsa_private_key_der_prefix_status(material: str) -> Tuple[bool, bool]:
    """Return whether *material* can be, and confirms, PKCS#1 RSA DER.

    Traditional unencrypted RSA PEM contains a DER SEQUENCE whose first child
    is the version INTEGER 0 or 1. Checking that prefix keeps arbitrary
    base64-shaped prose from becoming key evidence while accepting whitespace
    and physical-line wrapping anywhere in the encoded stream.
    """
    decoded = _decoded_base64_prefix(material)
    if decoded is None:
        return False, False
    if not decoded:
        return material == "M", False
    if decoded[0] != 0x30:
        return False, False
    if len(decoded) == 1:
        return True, False

    length_byte = decoded[1]
    if length_byte < 0x80:
        content_offset = 2
        content_length = length_byte
    else:
        length_octets = length_byte & 0x7F
        if length_octets == 0 or length_octets > 4:
            return False, False
        length_end = 2 + length_octets
        if len(decoded) < length_end:
            return True, False
        length_bytes = decoded[2:length_end]
        if length_bytes[0] == 0:
            return False, False
        content_length = int.from_bytes(length_bytes, "big")
        if content_length < 0x80:
            return False, False
        content_offset = length_end

    if content_length < 3:
        return False, False
    expected_integer = b"\x02\x01"
    available_integer = decoded[content_offset : content_offset + len(expected_integer)]
    if not expected_integer.startswith(available_integer):
        return False, False
    version_offset = content_offset + len(expected_integer)
    if len(decoded) <= version_offset:
        return True, False
    if decoded[version_offset] not in (0, 1):
        return False, False
    return True, True


def _pem_context_segments(
    candidate: str, end_marker: str = _PEM_END_MARKER
) -> Tuple[List[Optional[str]], bool, bool]:
    """Classify one bounded physical PEM-context line.

    Returns normalized base64-shaped logical lines, ``None`` for non-payload
    logical lines, whether *end_marker* was reached, and whether legacy PEM
    encryption metadata was present. Empty lines and exact metadata are
    neutral.
    """
    bounded = candidate[:_PEM_LOOKAHEAD_CHARS_PER_LINE]
    marker_index = bounded.find(end_marker)
    reached_end_marker = marker_index >= 0
    if reached_end_marker:
        bounded = bounded[:marker_index]

    segments: List[Optional[str]] = []
    saw_encryption_metadata = False
    for logical_line in _PEM_SERIALIZED_LINE_BREAK.split(bounded):
        # JSON permits escaping a solidus, and serialized PEM whitespace can
        # appear as a tab or Unicode space escape. Decode only those bounded,
        # payload-safe spellings before validating the complete base64 line.
        logical_line = _PEM_SERIALIZED_SOLIDUS.sub("/", logical_line)
        logical_line = _PEM_SERIALIZED_HORIZONTAL_SPACE.sub(" ", logical_line)
        if _PEM_METADATA_FIELD.search(logical_line):
            saw_encryption_metadata = True
        without_metadata = _PEM_METADATA_FIELD.sub("", logical_line)
        undecorated = without_metadata.strip(_PEM_LINE_DECORATION)
        if not undecorated:
            continue
        payload = _pem_payload_text(undecorated)
        if payload is None:
            segments.append(None)
            continue
        segments.append(payload)
    return segments, reached_end_marker, saw_encryption_metadata


def _unencrypted_material_with_segment(material: str, segment: str) -> str:
    """Append *segment* when the aggregate remains a possible RSA DER prefix."""
    combined = material + segment
    if _PEM_BASE64_LINE.fullmatch(combined):
        possible, _confirmed = _rsa_private_key_der_prefix_status(combined)
        if possible:
            return combined
    if material and _PEM_BASE64_LINE.fullmatch(segment):
        possible, _confirmed = _rsa_private_key_der_prefix_status(segment)
        if possible:
            return segment
    return ""


def _encrypted_material_is_credible(material: str) -> bool:
    """Whether legacy encrypted PEM has a complete ciphertext-sized prefix."""
    if len(material.rstrip("=")) < _PEM_ENCRYPTED_MATERIAL_MIN_CHARS:
        return False
    # A traditional encrypted RSA key is much longer than one 64-character
    # PEM line. Requiring one complete base64 quantum line avoids treating a
    # handful of standalone prose headings as ciphertext while retaining
    # arbitrary physical-line and intra-line whitespace wrapping.
    prefix = material[:_PEM_ENCRYPTED_MATERIAL_MIN_CHARS]
    try:
        base64.b64decode(prefix, validate=True)
    except (binascii.Error, ValueError):
        return False
    return _shannon_entropy(prefix) >= _PEM_ENCRYPTED_MATERIAL_MIN_ENTROPY


def _pem_material_progress(state: _PemMaterialState, candidate: str) -> Tuple[bool, bool]:
    """Advance one bounded candidate, resetting at non-payload segments."""
    segments, reached_end_marker, saw_encryption_metadata = _pem_context_segments(candidate)
    state.encrypted = state.encrypted or saw_encryption_metadata
    for segment in segments:
        if segment is None:
            state.material = ""
            continue
        if state.encrypted:
            combined = state.material + segment
            state.material = combined if _PEM_BASE64_LINE.fullmatch(combined) else segment
            _possible, confirms_der = _rsa_private_key_der_prefix_status(state.material)
            detected = _encrypted_material_is_credible(state.material) or (
                len(state.material.rstrip("=")) >= _PEM_KEY_MATERIAL_MIN_CHARS and confirms_der
            )
        else:
            state.material = _unencrypted_material_with_segment(state.material, segment)
            _possible, confirmed = _rsa_private_key_der_prefix_status(state.material)
            detected = len(state.material.rstrip("=")) >= _PEM_KEY_MATERIAL_MIN_CHARS and confirmed
        if detected:
            return reached_end_marker, True
    return reached_end_marker, False


def _pem_material_follows_header(
    lines: List[str],
    line_index: int,
    match: re.Match,
    budget: _PemScanBudget,
) -> bool:
    """Whether a non-RSA PEM header introduces base64 key material.

    The RSA detector confirms a DER prefix; other key encodings have no one
    prefix to confirm, so credible material is a base64 run at least
    ``_PEM_KEY_MATERIAL_MIN_CHARS`` long before the matching end marker.
    Any non-payload line resets the run, so a list of headers a security
    skill scans for never accumulates material from its neighbours.
    """
    header = match.group(0)
    end_marker = header.replace("-----BEGIN ", "-----END ", 1)
    remainder = lines[line_index][match.end() :]
    remainder_truncated = len(remainder) > _PEM_LOOKAHEAD_CHARS_PER_LINE
    lookahead_end = min(len(lines), line_index + 1 + _PEM_LOOKAHEAD_PHYSICAL_LINES)
    candidates = [remainder] + lines[line_index + 1 : lookahead_end]
    material = 0
    for position, candidate in enumerate(candidates):
        truncated = (
            remainder_truncated
            if position == 0
            else (len(candidate) > _PEM_LOOKAHEAD_CHARS_PER_LINE)
        )
        candidate = candidate[:_PEM_LOOKAHEAD_CHARS_PER_LINE]
        if not budget.claim(candidate):
            return True
        segments, reached_end_marker, _metadata = _pem_context_segments(candidate, end_marker)
        for segment in segments:
            if segment is None:
                material = 0
                continue
            material += len(segment.rstrip("="))
            if material >= _PEM_KEY_MATERIAL_MIN_CHARS:
                return True
        if reached_end_marker:
            return False
        if truncated:
            return True
    return False


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
    def _pem_key_material_follows(
        lines: List[str],
        line_index: int,
        match: re.Match,
        budget: Optional[_PemScanBudget] = None,
    ) -> bool:
        """Whether an RSA header introduces key material instead of teaching text."""
        if budget is None:
            budget = _PemScanBudget(_PEM_SCAN_MAX_CHARS_PER_BLOB)
        state = _PemMaterialState()
        remainder = lines[line_index][match.end() :]
        remainder_truncated = len(remainder) > _PEM_LOOKAHEAD_CHARS_PER_LINE
        remainder = remainder[:_PEM_LOOKAHEAD_CHARS_PER_LINE]
        if not budget.claim(remainder):
            return True
        reached_end_marker, detected = _pem_material_progress(state, remainder)
        if detected:
            return True
        if reached_end_marker:
            return False
        if remainder_truncated:
            return True

        # Seventy-two physical lines accommodate traditional encryption
        # metadata, a blank separator, and the 64 one-column base64 characters
        # needed for credible ciphertext evidence. The per-blob work budget
        # still bounds repeated headers in adversary-controlled text.
        lookahead_end = min(len(lines), line_index + 1 + _PEM_LOOKAHEAD_PHYSICAL_LINES)
        for following_index in range(line_index + 1, lookahead_end):
            candidate = lines[following_index]
            candidate_truncated = len(candidate) > _PEM_LOOKAHEAD_CHARS_PER_LINE
            candidate = candidate[:_PEM_LOOKAHEAD_CHARS_PER_LINE]
            if not budget.claim(candidate):
                return True
            reached_end_marker, detected = _pem_material_progress(state, candidate)
            if detected:
                return True
            if reached_end_marker:
                return False
            if candidate_truncated:
                return True
        return False

    @classmethod
    def _structured_match_reportable(
        cls,
        lines: List[str],
        line_index: int,
        match: re.Match,
        pem_budget: Optional[_PemScanBudget] = None,
    ) -> bool:
        """Keep structured-token exceptions exact and PEM-material aware.

        A structured token is high-confidence, so the only exemptions are
        an audited documentation literal, a PEM header with no key material
        after it, and a run of one repeated character — the shape every
        ``ghp_xxxx…`` placeholder has and no real token does. Substring
        placeholder markers deliberately do not apply here: a real token can
        contain ``test`` or ``fake`` by chance, and a structured match is
        the detector that finds real leaks.
        """
        value = match.group(0)
        line = lines[line_index]
        previous_char = line[match.start() - 1 : match.start()]
        next_char = line[match.end() : match.end() + 1]
        if _PEM_PRIVATE_KEY_HEADER_RE.match(value):
            if not _is_rsa_header_delimiter(previous_char) or not _is_rsa_header_delimiter(
                next_char
            ):
                # The header is embedded in a larger token, not standalone.
                return True
            if value == _RSA_PRIVATE_KEY_HEADER:
                return cls._pem_key_material_follows(lines, line_index, match, pem_budget)
            if pem_budget is None:
                pem_budget = _PemScanBudget(_PEM_SCAN_MAX_CHARS_PER_BLOB)
            return _pem_material_follows_header(lines, line_index, match, pem_budget)
        if _REPEATED_CHARACTER_RUN_RE.search(value):
            return False
        if not _is_known_example_value(value):
            return True

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

    def _scan_text(
        self,
        text: str,
        threshold: float,
        markers: Tuple[str, ...],
        line_overrides: Optional[Dict[int, str]] = None,
        prose: Optional[str] = None,
    ):
        """Yield ``(line_num, desc)`` for at most one violation per line.

        Structured tokens are scanned in *text*, the complete body: a real
        ``ghp_…`` token inside a fenced block is a real leak. The generic
        ``key = "value"`` patterns are scanned in *prose* — the same body with
        fences, code spans and comments blanked, line count preserved — so a
        ``password: "SecurePass123!"`` teaching example in a code sample is
        not reported. *prose* defaults to *text* for bodies without markdown.
        """
        active = patterns_matching_anywhere(text, self._PATTERNS)
        if not active:
            return
        # Split on "\n" only, not str.splitlines(), which also breaks on
        # U+2028/U+2029/NEL/VT/FF — block file-line translation counts "\n",
        # so those extra splits would misattribute a match to the wrong line
        # (a payload could plant a U+2028 to point the finding elsewhere).
        # read_body() has already normalized CRLF.
        lines = text.split("\n")
        prose_lines = lines if prose is None else prose.split("\n")
        pem_budget = _PemScanBudget(_PEM_SCAN_MAX_CHARS_PER_BLOB)
        for body_line, normalized_line in (line_overrides or {}).items():
            if 1 <= body_line <= len(lines):
                lines[body_line - 1] = normalized_line
        for line_index, line in enumerate(lines):
            line_num = line_index + 1
            prose_line = prose_lines[line_index] if line_index < len(prose_lines) else line
            for pattern, desc, is_generic in active:
                if not is_generic:
                    if any(
                        self._structured_match_reportable(lines, line_index, match, pem_budget)
                        for match in pattern.finditer(line)
                    ):
                        yield line_num, desc
                        break
                    continue
                if any(
                    self._generic_match_reportable(m.group(1), threshold, markers)
                    for m in pattern.finditer(prose_line)
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
            ordered_list_lines = (
                dict(cf.markdown.ordered_list_content_lines())
                if _RSA_PRIVATE_KEY_HEADER in body
                else None
            )
            prose = cf.read_body(strip_code_blocks=True)
            for line_num, desc in self._scan_text(
                body, threshold, markers, ordered_list_lines, prose=prose
            ):
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
            ordered_list_lines = (
                dict(MarkdownDoc(text).ordered_list_content_lines())
                if _RSA_PRIVATE_KEY_HEADER in text
                else None
            )
            for _line_num, desc in self._scan_text(text, threshold, markers, ordered_list_lines):
                violations.append(
                    self.violation(
                        f"Potential secret detected in frontmatter " f"field '{fld.name}': {desc}",
                        file_path=fld.path,
                        line=fld.field_line,
                    )
                )
                break
        return violations

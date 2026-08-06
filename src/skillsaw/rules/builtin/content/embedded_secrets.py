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
    DEFAULT_PLACEHOLDER_MARKERS,
    STRUCTURED_SECRET_PATTERNS,
    is_secret_placeholder,
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
                "ghp_…, private keys) are always reported"
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

    # Each entry is (compiled_pattern, description, is_generic).  Structured
    # token formats are high-confidence and always reported.  Generic
    # assignment patterns capture the candidate value in group 1 and are
    # gated by the placeholder allowlist and entropy threshold.
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
        extra = self.config.get("additional-placeholders", [])
        if not isinstance(extra, list):
            return DEFAULT_PLACEHOLDER_MARKERS
        return DEFAULT_PLACEHOLDER_MARKERS + tuple(str(m).lower() for m in extra if str(m))

    @staticmethod
    def _is_placeholder(value: str, markers: Tuple[str, ...]) -> bool:
        """True when *value* is clearly a placeholder, not a real secret."""
        return is_secret_placeholder(value, markers)

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
        for line_num, line in enumerate(text.split("\n"), 1):
            for pattern, desc, is_generic in active:
                if not is_generic:
                    if pattern.search(line):
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

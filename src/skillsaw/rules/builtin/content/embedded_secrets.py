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

# Default minimum Shannon entropy (bits/char) a generic ``key = "value"``
# candidate must reach before it is reported.  Random secrets (base64, hex,
# mixed-character passwords) comfortably exceed this; English-ish placeholder
# strings mostly do not.  Structured token formats (AKIA…, ghp_…, private-key
# blocks) are high-confidence and are never entropy-gated.
_DEFAULT_ENTROPY_THRESHOLD = 3.5

# Case-insensitive substrings that mark a generic credential value as an
# obvious placeholder (inspired by gitleaks/detect-secrets allowlists).
_PLACEHOLDER_MARKERS = (
    "example",
    "placeholder",
    "dummy",
    "sample",
    "changeme",
    "change-me",
    "change_me",
    "your-",
    "your_",
    "hunter2",
    "password",
    "passwd",
    "secret",
    "token",
    "test",
    "fake",
    "foobar",
    "redacted",
    "insert",
    "todo",
    "fixme",
    "xxx",
)

# Template/variable syntax anywhere in the value marks it as a placeholder:
# <your-key>, ${API_KEY}, {{ secrets.KEY }}, $VAR interpolation.
_TEMPLATE_SYNTAX = re.compile(r"<[^>]*>|\$\{[^}]*\}|\{\{[^}]*\}\}|\$[A-Z_][A-Z0-9_]*")


def _shannon_entropy(value: str) -> float:
    """Shannon entropy of *value* in bits per character."""
    if not value:
        return 0.0
    length = len(value)
    counts = {}
    for ch in value:
        counts[ch] = counts.get(ch, 0) + 1
    return -sum((n / length) * math.log2(n / length) for n in counts.values())


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
    _PATTERNS = [
        (re.compile(p), desc, generic)
        for p, desc, generic in [
            # OpenAI / Anthropic
            (r"\bsk-[a-zA-Z0-9]{20,}", "OpenAI/Anthropic API key", False),
            (r"\bsk-ant-[a-zA-Z0-9\-_]{20,}", "Anthropic API key", False),
            # GitHub
            (r"\bghp_[a-zA-Z0-9]{36,}", "GitHub personal access token", False),
            (r"\bghs_[a-zA-Z0-9]{36,}", "GitHub server token", False),
            (r"\bgho_[a-zA-Z0-9]{36,}", "GitHub OAuth token", False),
            (r"\bghu_[a-zA-Z0-9]{36,}", "GitHub user token", False),
            (r"\bghr_[a-zA-Z0-9]{36,}", "GitHub refresh token", False),
            # GitLab
            (r"\bglpat-[a-zA-Z0-9\-_]{20,}", "GitLab personal access token", False),
            # AWS
            (r"\bAKIA[0-9A-Z]{16}", "AWS access key ID", False),
            (r"\bASIA[0-9A-Z]{16}", "AWS temporary access key ID", False),
            # Slack
            (r"\bxoxb-[0-9]{10,}-[0-9a-zA-Z\-]+", "Slack bot token", False),
            (r"\bxoxp-[0-9]{10,}-[0-9a-zA-Z\-]+", "Slack user token", False),
            (r"\bxoxa-[0-9]{10,}-[0-9a-zA-Z\-]+", "Slack app token", False),
            (r"\bxoxr-[0-9]{10,}-[0-9a-zA-Z\-]+", "Slack refresh token", False),
            # Stripe
            (r"\bsk_live_[a-zA-Z0-9]{24,}", "Stripe secret key", False),
            (r"\brk_live_[a-zA-Z0-9]{24,}", "Stripe restricted key", False),
            # Google
            (r"\bAIza[0-9A-Za-z_\-]{35}", "Google API key", False),
            # Twilio
            (r"\bSK[0-9a-fA-F]{32}", "Twilio API key", False),
            # SendGrid
            (r"\bSG\.[a-zA-Z0-9_\-]{22}\.[a-zA-Z0-9_\-]{43}", "SendGrid API key", False),
            # npm
            (r"\bnpm_[a-zA-Z0-9]{36}", "npm access token", False),
            # PyPI
            (r"\bpypi-[a-zA-Z0-9]{16,}", "PyPI API token", False),
            # JWT (base64.base64.base64)
            (
                r"\beyJ[a-zA-Z0-9_\-]*\.eyJ[a-zA-Z0-9_\-]*\.[a-zA-Z0-9_\-]+",
                "JSON Web Token",
                False,
            ),
            # Private keys
            (r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----", "Private key", False),
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
            return _PLACEHOLDER_MARKERS
        return _PLACEHOLDER_MARKERS + tuple(str(m).lower() for m in extra if str(m))

    @staticmethod
    def _is_placeholder(value: str, markers: Tuple[str, ...]) -> bool:
        """True when *value* is clearly a placeholder, not a real secret."""
        if len(set(value)) <= 1:
            return True  # all-same-character: ********, aaaaaaaa
        if _TEMPLATE_SYNTAX.search(value):
            return True  # <your-key>, ${API_KEY}, {{ secrets.KEY }}, $VAR
        lowered = value.lower()
        return any(marker in lowered for marker in markers)

    def _generic_match_reportable(
        self, value: Optional[str], threshold: float, markers: Tuple[str, ...]
    ) -> bool:
        """Gate a generic ``key = "value"`` candidate: skip obvious
        placeholders and low-entropy (English-ish) strings."""
        if value is None:
            return False
        if self._is_placeholder(value, markers):
            return False
        return _shannon_entropy(value) >= threshold

    def _scan_text(self, text: str, threshold: float, markers: Tuple[str, ...]):
        """Yield ``(line_num, desc)`` for at most one violation per line."""
        active = patterns_matching_anywhere(text, self._PATTERNS)
        if not active:
            return
        for line_num, line in enumerate(text.splitlines(), 1):
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

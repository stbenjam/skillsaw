"""Small, conservative text redaction helpers for locally shared artifacts.

This module deliberately has no dependency on the lint tree or a third-party
secret scanner.  Callers that write logs, diagnostic bundles, or other
user-shareable text can use the same high-confidence patterns as the secret
rules while retaining control of which files they choose to include.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Pattern, Tuple

# High-confidence structured token formats. These are intentionally shared by
# prose and structured-config rules; generic ``key = value`` detection remains
# caller-specific because its acceptable false-positive tradeoff differs.
STRUCTURED_SECRET_PATTERNS: Tuple[Tuple[Pattern[str], str], ...] = tuple(
    (re.compile(pattern), description)
    for pattern, description in (
        # OpenAI / Anthropic
        (r"\bsk-[a-zA-Z0-9]{20,}", "OpenAI/Anthropic API key"),
        (r"\bsk-ant-[a-zA-Z0-9\-_]{20,}", "Anthropic API key"),
        # GitHub
        (r"\bghp_[a-zA-Z0-9]{36,}", "GitHub personal access token"),
        (r"\bghs_[a-zA-Z0-9]{36,}", "GitHub server token"),
        (r"\bgho_[a-zA-Z0-9]{36,}", "GitHub OAuth token"),
        (r"\bghu_[a-zA-Z0-9]{36,}", "GitHub user token"),
        (r"\bghr_[a-zA-Z0-9]{36,}", "GitHub refresh token"),
        # GitLab
        (r"\bglpat-[a-zA-Z0-9\-_]{20,}", "GitLab personal access token"),
        # AWS
        (r"\bAKIA[0-9A-Z]{16}", "AWS access key ID"),
        (r"\bASIA[0-9A-Z]{16}", "AWS temporary access key ID"),
        # Slack
        (r"\bxoxb-[0-9]{10,}-[0-9a-zA-Z\-]+", "Slack bot token"),
        (r"\bxoxp-[0-9]{10,}-[0-9a-zA-Z\-]+", "Slack user token"),
        (r"\bxoxa-[0-9]{10,}-[0-9a-zA-Z\-]+", "Slack app token"),
        (r"\bxoxr-[0-9]{10,}-[0-9a-zA-Z\-]+", "Slack refresh token"),
        # Stripe
        (r"\bsk_live_[a-zA-Z0-9]{24,}", "Stripe secret key"),
        (r"\brk_live_[a-zA-Z0-9]{24,}", "Stripe restricted key"),
        # Google
        (r"\bAIza[0-9A-Za-z_\-]{35}", "Google API key"),
        # Twilio
        (r"\bSK[0-9a-fA-F]{32}", "Twilio API key"),
        # SendGrid
        (r"\bSG\.[a-zA-Z0-9_\-]{22}\.[a-zA-Z0-9_\-]{43}", "SendGrid API key"),
        # npm
        (r"\bnpm_[a-zA-Z0-9]{36}", "npm access token"),
        # PyPI
        (r"\bpypi-[a-zA-Z0-9]{16,}", "PyPI API token"),
        # JWT (base64.base64.base64)
        (
            r"\beyJ[a-zA-Z0-9_\-]*\.eyJ[a-zA-Z0-9_\-]*\.[a-zA-Z0-9_\-]+",
            "JSON Web Token",
        ),
        # Private keys
        (r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----", "Private key"),
    )
)

CREDENTIAL_FIELD_NAMES = frozenset(
    {
        "api_key",
        "api_token",
        "access_key",
        "access_key_id",
        "access_token",
        "auth_token",
        "bearer_token",
        "client_secret",
        "credential",
        "credentials",
        "password",
        "passwd",
        "passphrase",
        "private_key",
        "refresh_token",
        "secret",
        "secret_key",
        "session_token",
    }
)
CREDENTIAL_FIELD_SUFFIXES = tuple(f"_{name}" for name in CREDENTIAL_FIELD_NAMES)
_REDACTION_CREDENTIAL_FIELD_NAMES = CREDENTIAL_FIELD_NAMES | {"token"}
# A credential field name is matched at identifier-word boundaries: an optional
# separated prefix and suffix around the name itself. Matching an arbitrary
# substring would classify ordinary AI settings such as ``max_tokens`` or
# ``tokenizer`` as credentials and strip values a bug report needs.
_CREDENTIAL_NAME_FRAGMENT = "|".join(
    re.escape(name).replace("_", "[_-]")
    for name in sorted(_REDACTION_CREDENTIAL_FIELD_NAMES, key=len, reverse=True)
)
_CREDENTIAL_FIELD = (
    rf"[\"']?(?:[A-Za-z0-9_.-]*[_.-])?(?:{_CREDENTIAL_NAME_FRAGMENT})"
    r"(?:[_.-][A-Za-z0-9_.-]*)?[\"']?"
)
# A UTF-8 BOM survives ``read_text(encoding="utf-8")``, so it has to be allowed
# before the indentation of the first field or that field is never redacted.
_LINE_START = r"^\ufeff?[ \t]*"
# A plain YAML scalar runs to its comment or structural boundary, not to the
# first space: stopping early leaves most of a multiword credential in place.
_PLAIN_SCALAR = r"[^\s,}\]\r\n#]+(?:[ \t]+[^\s,}\]\r\n#]+)*"
_CREDENTIAL_ASSIGNMENT = re.compile(
    rf"(?im)(?P<prefix>(?:{_LINE_START}|(?<=[{{,\[])[ \t]*|{_LINE_START}-[ \t]+)"
    rf"{_CREDENTIAL_FIELD}[ \t]*[:=][ \t]*)(?P<value>"
    rf'\[REDACTED\]|"(?:\\.|[^"\\\r\n])*"|\'(?:\\.|[^\'\\\r\n])*\'|{_PLAIN_SCALAR})'
)
_AUTHORIZATION_HEADER = re.compile(
    rf"(?im)(?P<prefix>{_LINE_START}(?:proxy-)?authorization[ \t]*[:=][ \t]*)"
    r"(?P<value>[^\r\n]+)"
)
_BEARER_TOKEN = re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/-]{12,}")
_URL_USERINFO = re.compile(r"(?://)([^/\s:@]+(?::[^@/\s]+)?@)")
_PEM_BEGIN = r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----"
_PEM_PRIVATE_KEY = re.compile(
    rf"{_PEM_BEGIN}.*?-----END (?:[A-Z0-9 ]+ )?PRIVATE KEY-----",
    re.DOTALL,
)
# A truncated excerpt — a log tail cut mid-key — has no footer, so the complete
# pattern above misses it and only the header would be replaced. Consume the
# body through the last line that still looks like PEM content instead.
_PEM_KEY_LINE = r"\r?\n[ \t]*(?:[A-Za-z][A-Za-z0-9-]*:[^\r\n]*|[A-Za-z0-9+/=]+)[ \t]*(?=\r?\n|\Z)"
_PEM_TRUNCATED_KEY = re.compile(rf"{_PEM_BEGIN}(?:(?:\r?\n[ \t]*)*{_PEM_KEY_LINE})*")
_BLOCK_SCALAR_CREDENTIAL = re.compile(
    rf"{_LINE_START}(?P<dash>-[ \t]+)?(?P<key>{_CREDENTIAL_FIELD})[ \t]*:[ \t]*[>|][^\n]*$",
    re.IGNORECASE,
)
_REDACTED = "[REDACTED]"


@dataclass(frozen=True)
class RedactionResult:
    """The text safe to share and the number of values that changed."""

    text: str
    count: int


def redact_text(text: str) -> RedactionResult:
    """Redact high-confidence credentials while preserving useful context.

    Multiline YAML scalars are handled structurally before line-oriented
    patterns, avoiding partial replacement or consumption of sibling fields.
    Calling this function repeatedly does not change already-redacted text.
    """
    redactions = 0

    def replacement(match: re.Match[str]) -> str:
        nonlocal redactions
        redactions += 1
        return _REDACTED

    text, _count = _PEM_PRIVATE_KEY.subn(replacement, text)
    text, _count = _PEM_TRUNCATED_KEY.subn(replacement, text)
    text, block_redactions = _redact_block_scalars(text)
    redactions += block_redactions

    def redact_assignment(match: re.Match[str]) -> str:
        nonlocal redactions
        value = match.group("value")
        if _already_redacted(value):
            return match.group(0)
        redactions += 1
        return f"{match.group('prefix')}{_marker_for(value)}"

    def redact_bearer(match: re.Match[str]) -> str:
        nonlocal redactions
        if match.group(0).endswith(_REDACTED):
            return match.group(0)
        redactions += 1
        return f"{match.group(1)}{_REDACTED}"

    def redact_userinfo(match: re.Match[str]) -> str:
        nonlocal redactions
        if match.group(1) == f"{_REDACTED}@":
            return match.group(0)
        redactions += 1
        return f"//{_REDACTED}@"

    for pattern, _description in STRUCTURED_SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    text = _CREDENTIAL_ASSIGNMENT.sub(redact_assignment, text)
    text = _AUTHORIZATION_HEADER.sub(redact_assignment, text)
    text = _BEARER_TOKEN.sub(redact_bearer, text)
    text = _URL_USERINFO.sub(redact_userinfo, text)
    return RedactionResult(text, redactions)


def _redact_block_scalars(text: str) -> tuple[str, int]:
    lines = text.splitlines(keepends=True)
    redacted_lines: list[str] = []
    redactions = 0
    index = 0
    while index < len(lines):
        line = lines[index]
        header = _BLOCK_SCALAR_CREDENTIAL.match(line.rstrip("\r\n"))
        if header is None:
            redacted_lines.append(line)
            index += 1
            continue
        redactions += 1
        ending = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
        # The key column, not the line indent: a sequence entry (``- password: |``)
        # puts its body past the dash, and a sibling entry sits at or before it.
        key_indent = header.start("key")
        prefix = line[:key_indent]
        redacted_lines.append(f"{prefix}{header.group('key')}: {_REDACTED}{ending}")
        index += 1
        while index < len(lines):
            candidate = lines[index]
            if candidate.strip() and len(candidate) - len(candidate.lstrip(" \t")) <= key_indent:
                break
            index += 1
    return "".join(redacted_lines), redactions


def _already_redacted(value: str) -> bool:
    return value.rstrip("\r") in {_REDACTED, f'"{_REDACTED}"', f"'{_REDACTED}'"}


def _marker_for(value: str) -> str:
    if value.startswith('"') and value.endswith('"'):
        return f'"{_REDACTED}"'
    if value.startswith("'") and value.endswith("'"):
        return f"'{_REDACTED}'"
    return _REDACTED

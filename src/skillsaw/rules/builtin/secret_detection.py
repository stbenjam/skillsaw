"""Pure, conservative helpers for detecting embedded credentials.

The content and structured-configuration rules share the high-confidence
token signatures here.  Keeping them independent of lint targets and rule
configuration lets callers apply the same detector without importing another
auto-discovered rule module.
"""

from __future__ import annotations

import re
from typing import Optional, Pattern, Sequence, Tuple

# Case-insensitive substrings that mark a generic credential value as an
# obvious placeholder (inspired by gitleaks/detect-secrets allowlists).
#
# Substring matching is deliberately aggressive, so every word here is a
# false-negative surface. Only words with demonstrated real-world placeholder
# value belong in this list. In particular, "secret" and "passwd" are not
# markers because they plausibly occur inside real credential values.
DEFAULT_PLACEHOLDER_MARKERS = (
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
# <your-key>, ${API_KEY}, {{ secrets.KEY }}. The angle-bracket form requires
# word-like placeholder content so incidental <..> punctuation inside a
# random secret does not suppress it.
_TEMPLATE_SYNTAX = re.compile(r"<[A-Za-z][A-Za-z0-9 _./-]{2,}>|\$\{[^}]*\}|\{\{[^}]*\}\}")

# Bare $VAR env-var interpolation. Matched greedily and confirmed in code:
# the character after the match must not be a lowercase letter, otherwise a
# random password containing "$MQ2vLp8" could be mistaken for a reference.
_ENV_VAR_SYNTAX = re.compile(r"\$[A-Z_][A-Z0-9_]{2,}")


def _has_env_var_reference(value: str) -> bool:
    """True when *value* contains a $VAR-style env-var reference."""
    for match in _ENV_VAR_SYNTAX.finditer(value):
        end = match.end()
        if end >= len(value) or not value[end].islower():
            return True
    return False


def is_secret_placeholder(value: str, markers: Sequence[str] = DEFAULT_PLACEHOLDER_MARKERS) -> bool:
    """Whether *value* is clearly a placeholder rather than a credential."""
    if not value.strip():
        return True
    if len(set(value)) <= 1:
        return True
    if _TEMPLATE_SYNTAX.search(value):
        return True
    if _has_env_var_reference(value):
        return True
    lowered = value.lower()
    return any(marker.lower() in lowered for marker in markers)


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


def structured_secret_description(value: str) -> Optional[str]:
    """Describe the first high-confidence structured secret in *value*."""
    for pattern, description in STRUCTURED_SECRET_PATTERNS:
        if pattern.search(value):
            return description
    return None


_ENV_CREDENTIAL_NAMES = frozenset(
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
_ENV_CREDENTIAL_SUFFIXES = tuple(f"_{name}" for name in _ENV_CREDENTIAL_NAMES)

_HEADER_CREDENTIAL_NAMES = frozenset(
    {
        "api_key",
        "authorization",
        "proxy_authorization",
        "x_access_token",
        "x_api_key",
        "x_auth_token",
        "x_client_secret",
    }
)
_HEADER_CREDENTIAL_SUFFIXES = (
    "_access_token",
    "_api_key",
    "_auth_token",
    "_authorization",
    "_bearer_token",
    "_client_secret",
    "_secret_key",
)
_NAME_SEPARATOR = re.compile(r"[^a-z0-9]+")


def _normalized_name(name: str) -> str:
    return _NAME_SEPARATOR.sub("_", name.casefold()).strip("_")


def _credential_name(name: str, *, header: bool) -> bool:
    normalized = _normalized_name(name)
    names = _HEADER_CREDENTIAL_NAMES if header else _ENV_CREDENTIAL_NAMES
    suffixes = _HEADER_CREDENTIAL_SUFFIXES if header else _ENV_CREDENTIAL_SUFFIXES
    return normalized in names or any(normalized.endswith(suffix) for suffix in suffixes)


def mapped_secret_description(
    name: str,
    value: str,
    *,
    header: bool,
    markers: Sequence[str] = DEFAULT_PLACEHOLDER_MARKERS,
) -> Optional[str]:
    """Describe a secret embedded in an MCP env/header mapping entry.

    Structured tokens are always reportable, including in a value that also
    contains a placeholder. Otherwise placeholders are permitted, and values
    under deliberately narrow credential-bearing names are treated as
    credentials even when they use an unknown token format. *markers* lets a
    caller extend the placeholder allowlist with a project's own convention;
    it never weakens the structured-token check above it. The return value
    never includes the candidate value.
    """
    structured = structured_secret_description(value)
    if structured is not None:
        return structured
    if is_secret_placeholder(value, markers):
        return None
    if _credential_name(name, header=header):
        return (
            "credential-bearing HTTP header"
            if header
            else "credential-bearing environment variable"
        )
    return None

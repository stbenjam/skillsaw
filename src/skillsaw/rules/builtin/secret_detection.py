"""Pure, conservative helpers for detecting embedded credentials.

The content and structured-configuration rules share the high-confidence
token signatures here.  Keeping them independent of lint targets and rule
configuration lets callers apply the same detector without importing another
auto-discovered rule module.
"""

from __future__ import annotations

import re
from typing import Any, Optional, Pattern, Sequence, Tuple
from urllib.parse import urlsplit

# ``scheme://…@`` ahead of any path/query/fragment — the structural shape of
# embedded user information.
_URL_USERINFO_RE = re.compile(r"://[^/?#]*@")

# WHATWG URL parsing — every browser and Node runtime — is lenient about the
# ``//`` after a special scheme: it accepts any slash run (backslashes too),
# so a JS client reads ``https:user:pass@example.com/mcp`` as user
# information for example.com while RFC 3986, and urlsplit with it, see one
# opaque path. Such spellings are retried in their normalized form.
_WHATWG_SPECIAL_SCHEME_RE = re.compile(r"^(https?|wss?|ftp|file):", re.IGNORECASE)


def url_has_userinfo(url: str) -> bool:
    """Whether a URL carries user information, even when malformed.

    urlsplit raises ValueError on some malformed URLs; the conservative
    fallback scans for the userinfo shape so an unparseable URL cannot
    smuggle embedded credentials past the check. Slashless special-scheme
    spellings are additionally retried the way a WHATWG client would
    normalize them.

    Shared by every rule that reads a server URL out of a configuration
    file, whichever host's dialect that file is written in.
    """

    def carries(candidate: str) -> bool:
        try:
            parsed = urlsplit(candidate)
        except ValueError:
            return _URL_USERINFO_RE.search(candidate) is not None
        return parsed.username is not None or parsed.password is not None

    if carries(url):
        return True
    match = _WHATWG_SPECIAL_SCHEME_RE.match(url)
    if not match:
        return False
    rest = url[match.end() :]
    if rest.startswith("//"):
        # Already in authority form — the first parse was authoritative.
        return False
    # The lstrip lives outside the f-string: a backslash in an expression
    # is a SyntaxError on the 3.9–3.11 interpreters this package supports.
    stripped = rest.lstrip("/\\")
    return carries(f"{match.group(0)}//{stripped}".replace("\\", "/"))


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

# Exact, well-known documentation/example values, compared case-insensitively
# after trimming surrounding whitespace. Keep these separate from the
# substring markers above: a credential merely containing one of these
# literals can still be real and must not inherit an allowlist exemption.
KNOWN_SECRET_EXAMPLE_VALUES = frozenset({"hunter2"})
_KNOWN_SECRET_EXAMPLE_VALUE_CASEFOLDS = frozenset(
    value.casefold() for value in KNOWN_SECRET_EXAMPLE_VALUES
)

# Template/variable syntax anywhere in the value marks it as a placeholder:
# <your-key>, ${API_KEY}, {{ secrets.KEY }}, and OpenCode's {env:API_KEY} /
# {file:./token}. The angle-bracket form requires word-like placeholder
# content so incidental <..> punctuation inside a random secret does not
# suppress it; the env/file forms name their scheme, which no credential
# does by accident.
_TEMPLATE_SYNTAX = re.compile(
    r"<[A-Za-z][A-Za-z0-9 _./-]{2,}>|\$\{[^}]*\}|\$\([^)]*\)|\{\{[^}]*\}\}"
    r"|\{(?:env|file):[^}]*\}"
)

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


def placeholder_markers(extra: Any) -> Tuple[str, ...]:
    """:data:`DEFAULT_PLACEHOLDER_MARKERS` extended by a rule's own config.

    Every rule taking an ``additional-placeholders`` option reads it through
    here, so they cannot disagree about what it accepts — otherwise the same
    ``.skillsaw.yaml`` line would suppress a finding in one rule and not
    another. Config values are not type-checked when the
    file loads, so any non-sequence contributes nothing rather than raising
    and costing the rule its findings; a sequence contributes its stringable
    members, lowercased for the case-insensitive match callers do.
    """
    if isinstance(extra, str) or not isinstance(extra, (list, tuple, set, frozenset)):
        return DEFAULT_PLACEHOLDER_MARKERS
    return DEFAULT_PLACEHOLDER_MARKERS + tuple(
        text.lower() for text in (str(marker) for marker in extra) if text
    )


def is_secret_placeholder(value: str, markers: Sequence[str] = DEFAULT_PLACEHOLDER_MARKERS) -> bool:
    """Whether *value* is clearly a placeholder rather than a credential."""
    if not value.strip():
        return True
    if value.strip().casefold() in _KNOWN_SECRET_EXAMPLE_VALUE_CASEFOLDS:
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
    kind: Optional[str] = None,
) -> Optional[str]:
    """Describe a secret embedded in a named MCP configuration value.

    Structured tokens are always reportable, including in a value that also
    contains a placeholder. Otherwise placeholders are permitted, and values
    under deliberately narrow credential-bearing names are treated as
    credentials even when they use an unknown token format. *markers* lets a
    caller extend the placeholder allowlist with a project's own convention;
    it never weakens the structured-token check above it. The return value
    never includes the candidate value.

    *kind* names what carried the value for a caller that is not scanning a
    map — a server-level scalar has no environment variable or header to
    name, and saying it does sends the author looking for one.
    """
    structured = structured_secret_description(value)
    if structured is not None:
        return structured
    if is_secret_placeholder(value, markers):
        return None
    if _credential_name(name, header=header):
        if kind is not None:
            return f"credential-bearing {kind}"
        return (
            "credential-bearing HTTP header"
            if header
            else "credential-bearing environment variable"
        )
    return None

"""Shared helpers for MCP Registry server.json validation."""

from __future__ import annotations

import hashlib
import re
from functools import lru_cache
from typing import Iterable, TYPE_CHECKING
from urllib.parse import urlsplit

from skillsaw.context import RepositoryType
from skillsaw.diagnostics import safe_display
from skillsaw.formats.mcp_registry import (
    MCP_REGISTRY_SCHEMA_VERSION,
    MCP_REGISTRY_SCHEMA_VERSIONS,
    load_mcp_registry_schema,
    mcp_registry_schema_version,
)

if TYPE_CHECKING:
    from jsonschema.exceptions import ValidationError


MCP_REGISTRY_REPO_TYPES = {RepositoryType.MCP_REGISTRY}

# Semantic Versioning 2.0.0. The released Registry schema deliberately permits
# non-semantic versions, so this is used by a warning rule rather than schema
# validity.
SEMVER = re.compile(
    r"\A(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?\Z"
)

_VERSION_ATOM = r"v?[0-9]+(?:\.[0-9]+){0,3}(?:-[0-9A-Za-z.-]+)?"
_COMPARATOR = rf"(?:\^|~|>=|<=|>|<|=)\s*{_VERSION_ATOM}"
_COMPARATOR_SET = rf"{_COMPARATOR}(?:\s+{_COMPARATOR})*"
_COMPARATOR_RANGE = re.compile(rf"\A\s*{_COMPARATOR_SET}\s*\Z")
_HYPHEN_RANGE = re.compile(rf"\A\s*{_VERSION_ATOM}\s-\s{_VERSION_ATOM}\s*\Z")
_DOTTED_VERSION_ATOM = r"(?:v?[0-9]+|[xX*])(?:\.(?:[0-9]+|[xX*])){1,2}" r"(?:-[0-9A-Za-z.-]+)?"
_DOTTED_VERSION = re.compile(rf"\A\s*{_DOTTED_VERSION_ATOM}\s*\Z")
_PYPI_SPECIFIER = re.compile(r"\A\s*(?:~=|==|!=|<=|>=|<|>|===)")
_NUGET_RANGE = re.compile(r"\A\s*[\[(].*[\])]\s*\Z")
_URL_TEMPLATE_VARIABLE = re.compile(r"\{[^{}\s]+\}")
_URI = re.compile(r"\A[A-Za-z][A-Za-z0-9+.-]*:" r"[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]*\Z")
_INVALID_PERCENT_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")


def is_version_range(value: str) -> bool:
    """Whether value uses a range/tag form forbidden by the Registry."""
    stripped = value.strip()
    if not stripped or stripped == "latest" or stripped in {"*", "x", "X"}:
        return True
    if "||" in stripped:
        return True
    if any(
        pattern.fullmatch(stripped) is not None for pattern in (_COMPARATOR_RANGE, _HYPHEN_RANGE)
    ):
        return True
    version_core = stripped.partition("-")[0]
    return _DOTTED_VERSION.fullmatch(stripped) is not None and any(
        component in {"x", "X", "*"} for component in version_core.lstrip("v").split(".")
    )


def is_package_version_range(registry_type: object, value: str) -> bool:
    """Recognize range syntax in the package registry's own vocabulary."""
    if is_version_range(value):
        return True
    stripped = value.strip()
    if registry_type == "pypi":
        # PEP 440 requirement specifiers may be comma-joined and may carry
        # environment markers. Neither form identifies one published file.
        return _PYPI_SPECIFIER.match(stripped) is not None or any(
            marker in stripped for marker in (",", ";")
        )
    if registry_type == "nuget":
        # NuGet interval and bracketed pin syntax belongs to dependency
        # ranges; publisher metadata takes the bare package version.
        return _NUGET_RANGE.fullmatch(stripped) is not None or "," in stripped
    if registry_type == "cargo":
        # Cargo joins multiple requirements with commas; the individual
        # comparator and wildcard forms are handled by is_version_range().
        return "," in stripped
    return False


def _is_uri(value: object) -> bool:
    """Validate RFC 3986 URI syntax without an optional dependency.

    jsonschema intentionally treats formats as annotations unless a checker
    is supplied, and its URI checker is also absent when the optional format
    extra is not installed. The Registry schema relies on URI fields, so its
    bundled validator provides the small syntax check directly.
    """
    if not isinstance(value, str):
        return True
    if (
        _URI.fullmatch(value) is None
        or _INVALID_PERCENT_ESCAPE.search(value) is not None
        or value.count("#") > 1
    ):
        return False
    try:
        parsed = urlsplit(value)
        # Accessing hostname and port performs structural validation that the
        # permissive splitter defers, including balanced IPv6 brackets and a
        # numeric, in-range port. Opaque URIs have no authority and remain
        # valid RFC 3986 references.
        if parsed.netloc:
            parsed.hostname
            parsed.port
    except ValueError:
        return False
    return True


def is_http_url_template(value: str) -> bool:
    """Validate an HTTP URL after safely standing in for template variables."""
    substituted = _URL_TEMPLATE_VARIABLE.sub("1", value)
    if "{" in substituted or "}" in substituted or not _is_uri(substituted):
        return False
    try:
        parsed = urlsplit(substituted)
        return parsed.scheme.lower() in {"http", "https"} and parsed.hostname is not None
    except ValueError:
        return False


def declares_unsupported_schema(data: object) -> bool:
    """Whether a Registry document canonically declares an unbundled version."""
    if not isinstance(data, dict):
        return False
    version = mcp_registry_schema_version(data.get("$schema"))
    return version is not None and version not in MCP_REGISTRY_SCHEMA_VERSIONS


# Importing jsonschema and compiling the validator costs measurable startup
# time. Repositories without Registry publisher metadata should pay neither.
@lru_cache(maxsize=None)
def registry_validator(schema_version: str = MCP_REGISTRY_SCHEMA_VERSION):
    """Return a cached validator for one bundled immutable schema version."""
    from jsonschema import FormatChecker
    from jsonschema.validators import validator_for
    from referencing import Registry

    checker = FormatChecker()
    checker.checks("uri")(_is_uri)
    schema = load_mcp_registry_schema(schema_version)
    validator_class = validator_for(schema, default=None)
    if validator_class is None:
        dialect = safe_display(schema.get("$schema"))
        raise RuntimeError(
            f"Bundled MCP Registry schema {schema_version!r} declares "
            f"unsupported JSON Schema dialect {dialect!r}"
        )
    validator_class.check_schema(schema)
    # An empty referencing registry fails closed for every non-local $ref;
    # Registry publisher metadata must never make validation retrieve a URL.
    return validator_class(schema, format_checker=checker, registry=Registry())


def format_schema_error(error: ValidationError) -> str:
    """Render a compact schema failure without echoing an untrusted value."""
    path = "$"
    for part in error.absolute_path:
        path += f"[{part}]" if isinstance(part, int) else f".{safe_display(part)}"
    if error.validator == "type":
        detail = f"must be of type {safe_display(error.validator_value)}"
    elif error.validator == "enum":
        choices = ", ".join(safe_display(value) for value in error.validator_value)
        detail = f"must be one of {choices}"
    elif error.validator == "pattern":
        detail = "does not match the required pattern"
    elif error.validator == "format":
        detail = f"must be a valid {safe_display(error.validator_value)}"
    elif error.validator == "minLength":
        detail = f"must contain at least {error.validator_value} character(s)"
    elif error.validator == "maxLength":
        detail = f"must contain at most {error.validator_value} character(s)"
    elif error.validator in {"anyOf", "oneOf"}:
        detail = "must match a permitted schema variant"
    elif error.validator == "not":
        detail = "uses a prohibited value"
    elif error.validator in {"required", "additionalProperties"}:
        # jsonschema's messages contain property names, not property values.
        detail = safe_display(error.message)
    else:
        detail = f"violates the {safe_display(error.validator)!r} constraint"
    return f"{path}: {detail}"


def schema_error_summary(errors: Iterable[ValidationError], *, limit: int = 4) -> str:
    """Summarize an error stream with bounded memory and deterministic order."""
    sample = []
    count = 0
    for error in errors:
        count += 1
        if len(sample) < limit:
            sample.append(error)
    sample.sort(key=lambda error: (tuple(map(str, error.absolute_path)), error.message))
    rendered = [format_schema_error(error) for error in sample]
    remaining = count - len(rendered)
    if remaining:
        rendered.append(f"and {remaining} more schema error{'s' if remaining != 1 else ''}")
    return "; ".join(rendered)


def stable_key(value: object) -> str:
    """Short stable identifier for an untrusted diagnostic discriminator."""
    return hashlib.sha256(str(value).encode("utf-8", errors="replace")).hexdigest()[:16]

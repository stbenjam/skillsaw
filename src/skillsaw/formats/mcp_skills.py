"""Vocabulary for Agent Skills served over MCP (SEP-2640).

The Skills extension (``io.modelcontextprotocol/skills``) publishes each file
of a skill directory as an MCP resource, conventionally at
``skill://<skill-path>/<file-path>``, and lists skills with ``skills/list`` /
``skills/get`` entries that carry the verbatim frontmatter and a manifest of
``{uri, digest, size}`` records. The skills themselves are plain Agent Skills;
this module holds only what ``skillsaw lint --mcp-server`` needs to fetch and
store them: the transport binding's constants and the mapping from resource
URIs to paths in a snapshot directory.
"""

from __future__ import annotations

import hashlib
import re
from typing import Optional, Tuple
from urllib.parse import unquote

EXTENSION_ID = "io.modelcontextprotocol/skills"
SKILL_SCHEME = "skill"
SKILL_FILENAME = "SKILL.md"

#: Per-skill limits every conforming host must accept (SEP-2640 "Limits").
MAX_RESOURCES_PER_SKILL = 512
MAX_BYTES_PER_SKILL = 16 * 1024 * 1024

DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

#: The record every fetch writes at the root of its output; ``skillsaw pull`` keeps it.
SNAPSHOT_FILENAME = "mcp-skills-snapshot.json"
SNAPSHOT_VERSION = 1

_LABEL_UNSAFE = re.compile(r"[^a-z0-9._-]+")
MAX_LABEL_LENGTH = 64
#: Names Windows resolves to devices in any directory, with any extension.
_WINDOWS_DEVICES = frozenset(
    ["con", "prn", "aux", "nul", "conin$", "conout$"]
    + [f"{port}{n}" for port in ("com", "lpt") for n in "123456789\u00b9\u00b2\u00b3"]
)


def _windows_device(name: str) -> bool:
    return name.split(".", 1)[0].rstrip(" ").lower() in _WINDOWS_DEVICES


def sanitize_label(value: str) -> str:
    """A single lowercase path segment naming a server inside a snapshot."""
    label = _LABEL_UNSAFE.sub("-", value.strip().lower()).strip(".-")
    label = label[:MAX_LABEL_LENGTH].rstrip(".-") or "server"
    if _windows_device(label):
        # Windows reads the name before the first dot, so change that part.
        label = f"server-{label}"[:MAX_LABEL_LENGTH].rstrip(".-")
    return label


def sha256_digest(data: bytes) -> str:
    """The extension's digest spelling for *data*."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _safe_segment(segment: str) -> Optional[str]:
    """Percent-decode one URI segment, or ``None`` if it is unsafe on disk.

    Beyond ``..`` and separators, Windows treats ``D:`` as a drive, ``a:b``
    as an alternate data stream, ``NUL`` or ``con.md`` as a device, refuses
    ``*?"<>|`` in names, and drops trailing dots and spaces — so ``.. ``
    would become ``..``. Those spellings are refused on every platform so a
    snapshot means the same thing wherever it is read.
    """
    decoded = unquote(segment)
    if decoded in ("", ".", ".."):
        return None
    if any(ch in decoded for ch in '/\\\x00:*?"<>|'):
        return None
    if decoded != decoded.rstrip(". ") or _windows_device(decoded):
        return None
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F or 0xD800 <= ord(ch) <= 0xDFFF for ch in decoded):
        return None  # control characters, or lone surrogates no filesystem can encode
    return decoded


def split_uri(uri: str) -> Optional[Tuple[str, Tuple[str, ...]]]:
    """``(scheme, decoded segments)`` of a hierarchical resource URI.

    The authority is the first segment, as the extension maps
    ``skill://acme/billing/refunds/SKILL.md``. Query strings, fragments and
    any segment that could escape a directory are rejected.
    """
    if not isinstance(uri, str) or "://" not in uri:
        return None
    scheme, _, rest = uri.partition("://")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9+.-]*", scheme):
        return None
    if "?" in rest or "#" in rest:
        return None
    segments = []
    for raw in rest.split("/"):
        segment = _safe_segment(raw)
        if segment is None:
            return None
        segments.append(segment)
    return scheme.lower(), tuple(segments)


def local_parts(uri: str) -> Optional[Tuple[str, ...]]:
    """Relative path parts at which a snapshot stores the resource *uri*.

    ``skill://`` URIs map to their segments; any other scheme is kept apart
    under ``_<scheme>/`` so it cannot collide with a ``skill://`` path.
    """
    split = split_uri(uri)
    if split is None:
        return None
    scheme, segments = split
    if scheme == SKILL_SCHEME:
        return segments
    return (f"_{scheme}",) + segments


def skill_root_uri(skill_md_uri: str) -> Optional[str]:
    """The skill directory URI for the URI of its ``SKILL.md``."""
    suffix = "/" + SKILL_FILENAME
    if not isinstance(skill_md_uri, str) or not skill_md_uri.endswith(suffix):
        return None
    root = skill_md_uri[: -len(suffix)]
    return root if "://" in root and not root.endswith("://") else None


def uri_skill_name(skill_md_uri: str) -> Optional[str]:
    """The final ``<skill-path>`` segment of a ``SKILL.md`` URI — the skill name."""
    split = split_uri(skill_md_uri)
    if split is None or len(split[1]) < 2 or split[1][-1] != SKILL_FILENAME:
        return None
    return split[1][-2]

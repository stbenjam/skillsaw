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
import ipaddress
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote

from ..paths import contained_resolve, safe_resolve

EXTENSION_ID = "io.modelcontextprotocol/skills"
SKILL_SCHEME = "skill"
SKILL_FILENAME = "SKILL.md"

#: Default per-server bounds for ``skillsaw lint/tree/pull --mcp-*``.
DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_SKILLS = 256
DEFAULT_MAX_BYTES = 64 * 1024 * 1024

#: Per-skill limits every conforming host must accept (SEP-2640 "Limits").
MAX_RESOURCES_PER_SKILL = 512
MAX_BYTES_PER_SKILL = 16 * 1024 * 1024

DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

#: The record every fetch writes at the root of its output; ``skillsaw pull`` keeps it.
SNAPSHOT_FILENAME = "mcp-skills-snapshot.json"
SNAPSHOT_VERSION = 1
#: The most of a snapshot record read from disk (prevents symlink/FIFO hangs).
MAX_SNAPSHOT_RECORD_BYTES = 64 * 1024 * 1024

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


def is_loopback_host(host: str) -> bool:
    """Whether *host* is a local loopback address or ``localhost``."""
    lowered = host.rstrip(".").lower()
    if lowered == "localhost" or lowered.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def local_parts(uri: str) -> Optional[Tuple[str, ...]]:
    """Relative path parts at which a snapshot stores the resource *uri*.

    ``skill://`` URIs map to their segments, escaping a first segment that
    starts with ``_`` by prepending another ``_`` (``_org`` -> ``__org``);
    any other scheme maps under ``_<scheme>/`` (always one leading ``_``
    followed by a letter), keeping the two namespaces disjoint.
    """
    split = split_uri(uri)
    if split is None:
        return None
    scheme, segments = split
    if scheme == SKILL_SCHEME:
        if segments and segments[0].startswith("_"):
            return (f"_{segments[0]}",) + segments[1:]
        return segments
    prefix = _safe_segment(f"_{scheme}")
    if prefix is None:
        return None
    return (prefix,) + segments


def read_snapshot_record(root: Path) -> Optional[Dict[str, Any]]:
    """Read ``mcp-skills-snapshot.json`` from *root*, or ``None`` if absent/invalid.

    Only a regular non-symlink file within :data:`MAX_SNAPSHOT_RECORD_BYTES` is
    read, so a symlink to ``/dev/zero`` or a FIFO cannot hang discovery or pull.
    """
    record = root / SNAPSHOT_FILENAME
    try:
        if record.is_symlink() or not record.is_file():
            return None
        with record.open("rb") as handle:
            raw = handle.read(MAX_SNAPSHOT_RECORD_BYTES + 1)
        if len(raw) > MAX_SNAPSHOT_RECORD_BYTES:
            return None
        data = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError, RecursionError):
        return None
    return data if isinstance(data, dict) else None


def snapshot_skill_dirs(root: Path) -> List[Path]:
    """Every valid, contained skill directory listed by *root*'s MCP snapshot.

    Reading the snapshot directly ensures nested SEP-2640 skills and skills
    under dot-prefixed or typically skipped directory names (``node_modules``,
    ``venv``, ``templates``) are never silently dropped by generic repository
    walk heuristics.
    """
    data = read_snapshot_record(root)
    if data is None:
        return []
    servers = data.get("servers")
    if not isinstance(servers, list):
        return []
    resolved_root = safe_resolve(root)
    if resolved_root is None:
        return []
    dirs: List[Path] = []
    seen = set()
    for server in servers:
        if not isinstance(server, dict):
            continue
        label = server.get("label")
        skills = server.get("skills")
        if (
            not isinstance(label, str)
            or sanitize_label(label) != label
            or not isinstance(skills, list)
        ):
            continue
        for entry in skills:
            if not isinstance(entry, dict):
                continue
            uri = entry.get("uri")
            parts = local_parts(uri) if isinstance(uri, str) else None
            if not parts or len(parts) < 2 or parts[-1] != SKILL_FILENAME:
                continue
            skill_dir = root.joinpath(label, *parts[:-1])
            skill_md = skill_dir / SKILL_FILENAME
            resolved_md = contained_resolve(skill_md, resolved_root)
            if resolved_md is None or not resolved_md.is_file():
                continue
            resolved_dir = contained_resolve(skill_dir, resolved_root)
            if resolved_dir is None or resolved_dir in seen:
                continue
            seen.add(resolved_dir)
            dirs.append(skill_dir)
    return dirs


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

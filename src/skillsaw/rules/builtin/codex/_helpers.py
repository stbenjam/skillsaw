"""Shared helpers for the OpenAI Codex plugin rules.

Spec: https://developers.openai.com/plugins/build/plugins
"""

import json
import re
from pathlib import Path
from typing import Optional

from skillsaw.context import RepositoryType
from skillsaw.paths import has_parent_traversal, is_absolute_path
from skillsaw.rules.builtin.utils import read_text

# A Codex marketplace repository contains the plugins it catalogs, so the
# plugin rules have to fire there too — the same reason PLUGIN_REPO_TYPES
# carries MARKETPLACE alongside SINGLE_PLUGIN. Without it, an explicit
# ``--type codex-marketplace`` run discovers every local plugin and then
# checks none of their manifests.
CODEX_PLUGIN_REPO_TYPES = {RepositoryType.CODEX_PLUGIN, RepositoryType.CODEX_MARKETPLACE}
CODEX_MARKETPLACE_REPO_TYPES = {RepositoryType.CODEX_MARKETPLACE}

# "Use a stable plugin `name` in kebab-case. Plugin hosts use it as the
# plugin identifier and component namespace."
# ``\Z``, not ``$``: ``$`` also matches immediately before a trailing
# newline, so ``"my-plugin\n"`` would pass as kebab-case and the
# registration autofix would write it into the published catalog.
KEBAB_CASE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*\Z")


# C0, DEL, C1, and the Unicode bidi overrides — any of them can reorder
# or hide message text in a terminal or a rendered SARIF viewer.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]")

# Everything a message needs to locate the defect fits comfortably here;
# an adversarial multi-kilobyte value must not become a multi-kilobyte
# diagnostic in a CI artifact.
_MAX_DISPLAY = 500


def _redact_userinfo(text: str) -> str:
    """Strip credential-shaped userinfo before every ``@`` in *text*.

    Covers scheme-full ("https://u:tok@h/x"), scheme-relative, bare
    ("u:tok@h/x"), and scp-style ("tok@github.com:o/r.git") spellings:
    the segment between the last ``/``/whitespace and an ``@`` is
    redacted when it carries a colon (credential shape) or when the text
    after the ``@`` looks host-like (a dot or colon before the next
    whitespace). Over-redacting an email-shaped value in a path field is
    the safe direction. A linear right-to-left scan — no regex, so there
    is nothing to backtrack, and no length cap for a long token to slip
    past.
    """
    if "@" not in text:
        return text
    out = []
    emitted = 0
    search_from = 0
    length = len(text)
    while True:
        at = text.find("@", search_from)
        if at == -1:
            out.append(text[emitted:])
            return "".join(out)
        start = max(text.rfind(ch, emitted, at) for ch in ("/", " ", "\t", "\n", "@")) + 1
        start = max(start, emitted)
        userinfo = text[start:at]
        if not userinfo:
            search_from = at + 1
            continue
        # Host inspection is capped: a host longer than any real one with
        # no whitespace is treated as host-like, which errs toward
        # redaction — the safe direction.
        head_limit = min(at + 1 + 512, length)
        host_head = text[at + 1 : head_limit]
        ws = next((i for i, ch in enumerate(host_head) if ch.isspace()), None)
        if ws is not None:
            host_head = host_head[:ws]
            host_like = "." in host_head or ":" in host_head
        else:
            host_like = "." in host_head or ":" in host_head or head_limit < length
        if ":" in userinfo or host_like:
            out.append(text[emitted:start])
            out.append("[redacted]")
            emitted = at
        search_from = at + 1


def safe_display(value: object) -> str:
    """A manifest value made safe to echo into a violation message.

    Reports are uploaded as CI artifacts and ingested as SARIF, so an
    author's pasted ``user:token@host`` URL must not ride along — the
    userinfo is redacted, keeping the locator. Control characters are
    replaced so a crafted value cannot smuggle terminal escapes through
    the text formatter, and the result is length-bounded.
    """
    text = _CONTROL_CHARS.sub("\N{REPLACEMENT CHARACTER}", str(value))
    text = _redact_userinfo(text)
    if len(text) > _MAX_DISPLAY:
        text = text[:_MAX_DISPLAY] + "…"
    return text


def reject_nonfinite_json_number(value: str) -> None:
    """Reject JavaScript number extensions that strict JSON does not allow.

    ``json.loads`` accepts ``NaN``/``Infinity``/``-Infinity`` by default;
    Codex's strict parser does not. Passed as ``parse_constant`` so both the
    validity rules and the registration fixer reject the same documents.
    """
    raise ValueError(f"non-finite JSON number: {value}")


def nonfinite_constant_error(file_path: Path) -> str:
    """The strict-JSON defect the lenient shared reader accepted, or ``""``.

    ``read_json()`` inherits Python's ``NaN``/``Infinity``/``-Infinity``
    extensions, but Codex's strict parser rejects them — and so does the
    registration fixer, so without this a document could pass validity yet
    refuse every fix. The substring test only gates the reparse; a quoted
    ``"NaN"`` inside a string value still parses cleanly here.
    """
    content = read_text(file_path)
    if content is None or ("NaN" not in content and "Infinity" not in content):
        return ""
    try:
        json.loads(content, parse_constant=reject_nonfinite_json_number)
    except ValueError as e:
        return str(e)
    return ""


def path_problem(value: str, root_label: str, root: Optional[Path] = None) -> Optional[str]:
    """Why *value* is not a usable manifest path, or ``None`` if it is.

    The Codex docs state manifest paths must "resolve relative to the
    plugin root, and stay inside the plugin root" (and, for marketplace
    sources, the marketplace root). Absolute paths and ``..`` traversal
    both break that guarantee; the missing ``./`` prefix is only a style
    nudge, so it is reported separately by callers.

    Lexical checks alone are not enough. ``./skills-link`` has no ``..``
    and is not absolute, yet it leaves the root entirely when
    ``skills-link`` is a symlink pointing outside it — and for a
    marketplace source that means discovering and "registering" a plugin
    that is not in the repository. When *root* is supplied the candidate
    is resolved against it and rejected unless it stays beneath it.
    """
    if is_absolute_path(value):
        return f"absolute path '{safe_display(value)}' — paths must be relative to the {root_label}"
    if has_parent_traversal(value):
        return (
            f"path '{safe_display(value)}' contains '..' — paths must stay inside the {root_label}"
        )
    if root is not None and escapes_root(value, root):
        return (
            f"path '{safe_display(value)}' resolves outside the {root_label} — check for a symlink"
        )
    return None


def escapes_root(value: str, root: Path) -> bool:
    """Whether *value* resolves outside *root* once symlinks are followed.

    A path that does not exist yet cannot escape through a link, so an
    unresolvable candidate is left to the caller's existence check. ``OSError``
    (a symlink loop, an unreadable parent) counts as an escape: the linter
    cannot prove containment, and failing closed is the safe direction for a
    check whose whole purpose is keeping discovery inside the root.
    """
    try:
        resolved_root = root.resolve()
        candidate = (root / value).resolve()
    except (OSError, ValueError, RuntimeError):
        # OSError: an unreadable parent, or a symlink loop on 3.13+.
        # RuntimeError: a symlink loop before 3.13. ValueError: an embedded
        # NUL. Containment cannot be proven in any of these cases, and
        # failing closed is the safe direction for a containment check.
        return True
    return candidate != resolved_root and not candidate.is_relative_to(resolved_root)

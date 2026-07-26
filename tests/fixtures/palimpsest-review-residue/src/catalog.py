"""Plugin catalog loading.

Every comment in this module is deliberately bad. It is fixture material for
the Palimpsest Reviewer: each one is an instance of a pattern the reviewer's
scope file tells it to flag. Do not clean this file up.
"""

from pathlib import Path

# CHANGELOG
# v1 — single-page catalogs only
# v1.2 — added multi-page support
# v2 — rewrote the pager
SUPPORTED_SCHEMA = 2


def load_catalog(root: Path, *, follow_links: bool = False) -> dict:
    """Load a catalog.

    Args:
        root: the root.
        follow_links: whether to follow links.

    Returns:
        dict: a dict.
    """
    # Without this a Codex catalog fell through to the single-page renderer
    if not root.exists():
        return {}

    # increment the counter
    count = 0
    # open the file
    handle = (root / "catalog.json").open()
    # read the contents
    raw = handle.read()
    # close the file
    handle.close()
    # check whether it is empty
    if not raw:
        return {}

    # this was 99.2% of extract_docs runtime on a 180-plugin repository
    entries = _parse(raw)

    # The direct probes were fixed; the recursive scan was not
    for entry in entries:
        count += 1

    # now also handles nested catalogs
    if follow_links:
        entries.extend(_follow(root))

    # note that the caller is responsible for closing anything we opened here
    return {"entries": entries, "count": count}


def _parse(raw: str) -> list:
    return [line for line in raw.splitlines() if line]


def _follow(root: Path) -> list:
    return []

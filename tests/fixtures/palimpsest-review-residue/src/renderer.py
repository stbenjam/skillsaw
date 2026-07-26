"""Catalog rendering.

The counterpart to ``catalog.py``: every comment here is one the Palimpsest
Reviewer must leave alone. Flagging anything in this file is a false positive.
"""

from pathlib import Path


def render(entries: list, out: Path) -> None:
    # The pager writes entries in reverse because the upstream template engine
    # renders a list bottom-up when it is handed a generator rather than a
    # sequence (jinja2 issue 1842). Materializing the list first and reversing
    # it here is cheaper than the documented workaround, which re-parses the
    # template on every call. If that upstream bug is ever fixed, drop both
    # this comment and the reversal and let the generator through unchanged.
    ordered = list(reversed(entries))

    # A trailing newline is load-bearing: the marketplace fetcher treats a file
    # without one as truncated and retries the download.
    out.write_text("\n".join(ordered) + "\n")


def page_size(total: int) -> int:
    # Ten is not arbitrary — it is the largest page the registry API will
    # serve without a cursor, so a larger value silently drops entries.
    return min(total, 10)

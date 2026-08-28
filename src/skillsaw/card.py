"""Self-contained SVG grade card for ``skillsaw badge --large``.

Renders a fixed-size (495x195 viewBox) card showing the repository name and
letter grade. The SVG must not churn when a repository's context size or
individual rule counts change without changing its grade.

Invariants:

- **Self-contained and offline.** No external fonts, images, scripts,
  stylesheets, or network references of any kind — the only URL in the
  output is the required ``xmlns`` namespace *identifier*, which is
  never fetched. The card renders identically from a README on GitHub
  (behind the camo image proxy) and from a local file.
- **Deterministic.** The output is a pure function of its inputs — no
  timestamps, random ids, or environment lookups — so regenerating the
  card only produces a diff when the underlying lint results change.
- **Fixed grading.** The card displays a :class:`skillsaw.grade.Grade`
  verbatim; the grading scale is deliberately not configurable so cards
  are comparable across repositories.
"""

from __future__ import annotations

import math
import unicodedata
from xml.sax.saxutils import escape

from .grade import LETTER_NOTCHES, LOGO_PATH, Grade

CARD_WIDTH = 495
CARD_HEIGHT = 195

# Hex equivalents of the shields.io named colors produced by Grade.color,
# so the card matches the repository's badge exactly.
SHIELDS_COLOR_HEX = {
    "brightgreen": "#44cc11",
    "green": "#97ca00",
    "yellow": "#dfb317",
    "orange": "#fe7d37",
    "red": "#e05d44",
}

# Generic system font stack — nothing is downloaded.
_FONTS = "'Segoe UI', Ubuntu, 'Helvetica Neue', Helvetica, Arial, sans-serif"

THEMES = {
    "light": {
        "bg": "#fffefe",
        "border": "#e4e2e2",
        "title": "#24292f",
        "text": "#434d58",
        "muted": "#768390",
    },
    "dark": {
        "bg": "#0d1117",
        "border": "#30363d",
        "title": "#e6edf3",
        "text": "#c9d1d9",
        "muted": "#8b949e",
    },
}

# Grade-ring geometry. The circumference is derived from the radius so
# the two can never drift apart; both are rendered rounded to 2 decimals.
_RING_RADIUS = 42
_RING_CIRCUMFERENCE = 2 * math.pi * _RING_RADIUS


def _char_width(ch: str) -> int:
    """Estimated display width of a glyph in ASCII-character columns.

    East-Asian Wide and Fullwidth glyphs (CJK, most emoji) render at
    roughly twice the advance width of an ASCII character in the card's
    proportional font stack, so they count double toward the layout budget.
    """
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def _display_width(text: str) -> int:
    return sum(_char_width(ch) for ch in text)


def _truncate(text: str, max_width: int) -> str:
    """Truncate *text* to an estimated display width, appending "…".

    ``max_width`` is a budget in ASCII-character columns (see
    :func:`_char_width`), not a character count.
    """
    if _display_width(text) <= max_width:
        return text
    width = 0
    for i, ch in enumerate(text):
        w = _char_width(ch)
        # Reserve one column for the ellipsis.
        if width + w > max_width - 1:
            return text[:i] + "…"
        width += w
    return text  # pragma: no cover — the early return above always fires


def render_card(
    grade: Grade,
    repo_name: str,
    theme: str = "dark",
) -> str:
    """Render a grade-focused SVG card.

    The card contains the repository name and grade.
    """
    if theme not in THEMES:
        raise ValueError(f"unknown theme {theme!r} (choose from {', '.join(sorted(THEMES))})")
    colors = THEMES[theme]
    # Defensive fallbacks: real Grade objects always yield a mapped color
    # and an on-scale letter, but a public function shouldn't crash on
    # unexpected inputs.
    accent = SHIELDS_COLOR_HEX.get(grade.color, "#888888")
    name = escape(_truncate(repo_name or "repository", 30))
    letter = escape(grade.letter)

    # Ring fill reflects the grade's position on the fixed notch scale
    # (A+ = full ring, F = empty). Letters off the scale draw the
    # empty (last-notch) ring.
    try:
        notch = LETTER_NOTCHES.index(grade.letter)
    except ValueError:
        notch = len(LETTER_NOTCHES) - 1
    fraction = 1.0 - notch / (len(LETTER_NOTCHES) - 1)

    # A zero-length dash with stroke-linecap="round" renders as a dot at
    # the 12 o'clock position (the standard SVG dotted-line technique),
    # so the empty ring omits the progress arc entirely instead of
    # drawing it with a zero dash.
    progress_arc = []
    if fraction > 0:
        dash = f"{fraction * _RING_CIRCUMFERENCE:.2f}"
        progress_arc = [
            (
                f'    <circle r="{_RING_RADIUS}" fill="none" stroke="{accent}"'
                f' stroke-width="7" stroke-linecap="round" transform="rotate(-90)"'
                f' stroke-dasharray="{dash} {_RING_CIRCUMFERENCE:.2f}"/>'
            )
        ]

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{CARD_WIDTH}"'
            f' height="{CARD_HEIGHT}" viewBox="0 0 {CARD_WIDTH} {CARD_HEIGHT}"'
            ' fill="none" role="img" aria-labelledby="card-title">'
        ),
        f'  <title id="card-title">skillsaw grade for {name}: {letter}</title>',
        "  <style>",
        f"    .title {{ font: 600 16px {_FONTS}; fill: {colors['title']}; }}",
        f"    .subtitle {{ font: 400 11px {_FONTS}; fill: {colors['muted']}; }}",
        f"    .grade-letter {{ font: 800 48px {_FONTS}; fill: {accent}; }}",
        "  </style>",
        (
            f'  <rect x="0.5" y="0.5" width="{CARD_WIDTH - 1}" height="{CARD_HEIGHT - 1}"'
            f' rx="4.5" fill="{colors["bg"]}" stroke="{colors["border"]}"/>'
        ),
        '  <g transform="translate(24, 17)">',
        f'    <path fill-rule="evenodd" fill="{accent}" d="{LOGO_PATH}"/>',
        "  </g>",
        f'  <text x="56" y="30" class="title" data-testid="repo-name">{name}</text>',
        '  <text x="56" y="46" class="subtitle">Agent Context Linter</text>',
        f'  <path d="M24 63.5H471" stroke="{colors["border"]}"/>',
        '  <g transform="translate(247.5, 127)">',
        (
            f'    <circle r="{_RING_RADIUS}" fill="none" stroke="{accent}"'
            ' stroke-opacity="0.25" stroke-width="7"/>'
        ),
        *progress_arc,
        (
            '    <text y="16" text-anchor="middle" class="grade-letter"'
            f' data-testid="grade-letter">{letter}</text>'
        ),
        "  </g>",
        "</svg>",
    ]
    return "\n".join(lines) + "\n"

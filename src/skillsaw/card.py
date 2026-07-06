"""Self-contained SVG report card for ``skillsaw badge --card``.

Renders a fixed-size (495x195 viewBox) github-readme-stats style card
showing the letter grade, weighted violation density, content-token
count, plugin/skill counts, and the top offending rules.

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

from typing import Sequence, Tuple
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

# Grade-ring geometry: radius 46 => circumference 2*pi*46.
_RING_RADIUS = 46
_RING_CIRCUMFERENCE = 289.03


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def _stat_row(y: int, label: str, value_markup: str) -> str:
    return (
        f'    <text x="24" y="{y}"><tspan class="label">{label}</tspan>'
        f'<tspan x="180" class="value">{value_markup}</tspan></text>'
    )


def render_card(
    grade: Grade,
    repo_name: str,
    plugin_count: int,
    skill_count: int,
    top_rules: Sequence[Tuple[str, int]],
    theme: str = "dark",
) -> str:
    """Render the report card as an SVG string.

    ``top_rules`` is a list of ``(rule_id, violation_count)`` pairs,
    most frequent first (``Counter.most_common(3)``); at most three are
    shown.
    """
    if theme not in THEMES:
        raise ValueError(f"unknown theme {theme!r} (choose from {', '.join(sorted(THEMES))})")
    colors = THEMES[theme]
    accent = SHIELDS_COLOR_HEX[grade.color]
    name = escape(_truncate(repo_name, 30))
    letter = escape(grade.letter)

    # Ring fill reflects the grade's position on the fixed notch scale
    # (A+ = full ring, F = nearly empty).
    notch = LETTER_NOTCHES.index(grade.letter)
    fraction = 1.0 - notch / (len(LETTER_NOTCHES) - 1)
    dash = f"{fraction * _RING_CIRCUMFERENCE:.2f}"

    rule_lines = []
    if top_rules:
        for i, (rule_id, count) in enumerate(list(top_rules)[:3]):
            label = escape(f"{i + 1}. {_truncate(rule_id, 40)} ({count})")
            rule_lines.append(
                f'    <text x="24" y="{154 + 14 * i}" class="rule"'
                f' data-testid="rule-{i}">{label}</text>'
            )
    else:
        rule_lines.append(
            '    <text x="24" y="154" class="rule" data-testid="rule-none">'
            "none — clean run</text>"
        )

    plugin_word = "plugin" if plugin_count == 1 else "plugins"
    skill_word = "skill" if skill_count == 1 else "skills"
    plugins_value = (
        f'<tspan data-testid="plugins">{plugin_count}</tspan> {plugin_word}'
        f' &#183; <tspan data-testid="skills">{skill_count}</tspan> {skill_word}'
    )

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{CARD_WIDTH}"'
            f' height="{CARD_HEIGHT}" viewBox="0 0 {CARD_WIDTH} {CARD_HEIGHT}"'
            ' fill="none" role="img" aria-labelledby="card-title">'
        ),
        f'  <title id="card-title">skillsaw report card for {name}: grade {letter}</title>',
        "  <style>",
        f"    .title {{ font: 600 16px {_FONTS}; fill: {colors['title']}; }}",
        f"    .subtitle {{ font: 400 11px {_FONTS}; fill: {colors['muted']}; }}",
        f"    .label {{ font: 600 13px {_FONTS}; fill: {colors['text']}; }}",
        f"    .value {{ font: 400 13px {_FONTS}; fill: {colors['text']}; }}",
        f"    .rule {{ font: 400 11.5px {_FONTS}; fill: {colors['muted']}; }}",
        f"    .grade-letter {{ font: 800 44px {_FONTS}; fill: {accent}; }}",
        "  </style>",
        (
            f'  <rect x="0.5" y="0.5" width="{CARD_WIDTH - 1}" height="{CARD_HEIGHT - 1}"'
            f' rx="4.5" fill="{colors["bg"]}" stroke="{colors["border"]}"/>'
        ),
        '  <g transform="translate(24, 17)">',
        f'    <path fill-rule="evenodd" fill="{accent}" d="{LOGO_PATH}"/>',
        "  </g>",
        f'  <text x="56" y="30" class="title" data-testid="repo-name">{name}</text>',
        '  <text x="56" y="46" class="subtitle">skillsaw report card</text>',
        '  <g data-testid="stats">',
        _stat_row(
            76,
            "Violation density",
            f'<tspan data-testid="density">{grade.density:.2f}</tspan> per 10k tokens',
        ),
        _stat_row(
            97,
            "Content tokens",
            f'~<tspan data-testid="tokens">{grade.content_tokens:,}</tspan>',
        ),
        _stat_row(118, "Building blocks", plugins_value),
        '    <text x="24" y="139" class="label">Top rules</text>',
        *rule_lines,
        "  </g>",
        '  <g transform="translate(415.5, 97.5)">',
        (
            f'    <circle r="{_RING_RADIUS}" fill="none" stroke="{accent}"'
            ' stroke-opacity="0.25" stroke-width="7"/>'
        ),
        (
            f'    <circle r="{_RING_RADIUS}" fill="none" stroke="{accent}"'
            f' stroke-width="7" stroke-linecap="round" transform="rotate(-90)"'
            f' stroke-dasharray="{dash} {_RING_CIRCUMFERENCE}"/>'
        ),
        (
            '    <text y="16" text-anchor="middle" class="grade-letter"'
            f' data-testid="grade-letter">{letter}</text>'
        ),
        "  </g>",
        "</svg>",
    ]
    return "\n".join(lines) + "\n"

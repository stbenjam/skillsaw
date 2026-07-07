"""
Repository quality grade.

The grade condenses a lint run into a letter (A+ .. F) suitable for a
README badge:

- **Violation density sets the letter.** Weighted violations (errors
  1.0, warnings 0.75, info 0.1) are normalized per 10,000 estimated
  content tokens, so a large marketplace is not penalized for having
  more surface area than a single skill. A+ requires density below
  1.0; after that every DENSITY_PER_NOTCH units cost a notch
  (A+ -> A -> A- -> ...).
- **Errors additionally knock off whole letters.** Errors are rare and
  structural — a broken manifest is not diluted by prose volume, so any
  error drops the grade a full letter regardless of repository size.
- Repositories smaller than one 10K-token unit are graded as one unit,
  so a tiny skill with a few warnings loses a notch rather than the
  whole scale.

Token estimates come from ``ContentBlock.estimate_tokens()`` (prose
blocks only); structured JSON config blocks are not content an agent
reads linearly and are excluded from the denominator.
"""

from dataclasses import dataclass
from typing import List

from .rule import RuleViolation, Severity

# The scoring constants are deliberately NOT configurable: a skillsaw
# badge must mean the same thing on every repository, and tunable
# weights would let a repo grade itself on a friendlier curve.
#
# A+ is exclusive (density < 1.0); after that each notch spans
# DENSITY_PER_NOTCH units. A whole letter is three notches.
# Calibrated against real repositories (June 2026): well-maintained
# community marketplaces run ~12-14 weighted violations per 10K tokens
# and should land around C+, not F.
LETTER_NOTCHES = ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D", "F"]
_NOTCHES_PER_LETTER = 3
A_PLUS_THRESHOLD = 1.0
DENSITY_PER_NOTCH = 2.0
ERROR_WEIGHT = 1.0
WARNING_WEIGHT = 0.75
INFO_WEIGHT = 0.1

TOKENS_PER_UNIT = 10_000

# Error-count brackets -> whole letters knocked off.
_ERROR_BRACKETS = ((25, 3), (5, 2), (1, 1))

# Minimal circular-saw-blade logo (8 hooked teeth, arbor hole) as a 24x24
# SVG path, reused by the README report card (skillsaw.card).
LOGO_PATH = (
    "M20.0 12.0L22.3 15.8L19.3 15.3"
    "L17.7 17.7L16.6 22.0L14.8 19.5L12.0 20.0L8.2 22.3L8.7 19.3L6.3 17.7"
    "L2.0 16.6L4.5 14.8L4.0 12.0L1.7 8.2L4.7 8.7L6.3 6.3L7.4 2.0L9.2 4.5"
    "L12.0 4.0L15.8 1.7L15.3 4.7L17.7 6.3L22.0 7.4L19.5 9.2Z"
    "M15.0 12.0A3.0 3.0 0 1 0 9.0 12.0A3.0 3.0 0 1 0 15.0 12.0Z"
)

# Standalone logo, white so it reads on the dark label half of the badge.
# Endpoint badges take the raw SVG via logoSvg; dynamic-json badges need it
# base64-encoded in the URL.
LOGO_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    f'<path fill-rule="evenodd" fill="#fff" d="{LOGO_PATH}"/></svg>'
)


def logo_data_uri() -> str:
    """data: URI for the logo, for shields.io URL ``logo=`` parameters."""
    import base64

    return "data:image/svg+xml;base64," + base64.b64encode(LOGO_SVG.encode()).decode()


# shields.io named colors per letter.
_LETTER_COLORS = {
    "A": "brightgreen",
    "B": "green",
    "C": "yellow",
    "D": "orange",
    "F": "red",
}


@dataclass
class Grade:
    letter: str
    density: float
    errors: int
    warnings: int
    info: int
    content_tokens: int

    @property
    def color(self) -> str:
        return _LETTER_COLORS[self.letter[0]]

    def to_dict(self) -> dict:
        return {
            "letter": self.letter,
            "density": round(self.density, 2),
            "content_tokens": self.content_tokens,
        }

    def badge_json(self) -> dict:
        """shields.io endpoint-schema payload. The schema rejects unknown
        properties, so only spec'd keys may appear here; dynamic-json
        badges read the grade via ``query=$.message``."""
        return {
            "schemaVersion": 1,
            "label": "skillsaw",
            "message": self.letter,
            "color": self.color,
            "logoSvg": LOGO_SVG,
        }


def _error_letters(errors: int) -> int:
    for threshold, letters in _ERROR_BRACKETS:
        if errors >= threshold:
            return letters
    return 0


def compute_grade(violations: List[RuleViolation], content_tokens: int) -> Grade:
    """Grade a lint run. ``content_tokens`` is the summed token estimate
    of every ContentBlock in the lint tree(s)."""
    errors = sum(1 for v in violations if v.severity == Severity.ERROR)
    warnings = sum(1 for v in violations if v.severity == Severity.WARNING)
    info = sum(1 for v in violations if v.severity == Severity.INFO)

    units = max(content_tokens / TOKENS_PER_UNIT, 1.0)
    density = (ERROR_WEIGHT * errors + WARNING_WEIGHT * warnings + INFO_WEIGHT * info) / units

    last = len(LETTER_NOTCHES) - 1
    if density < A_PLUS_THRESHOLD:
        notch = 0
    else:
        notch = min(1 + int((density - A_PLUS_THRESHOLD) / DENSITY_PER_NOTCH), last)
    notch = min(notch + _NOTCHES_PER_LETTER * _error_letters(errors), last)

    return Grade(
        letter=LETTER_NOTCHES[notch],
        density=density,
        errors=errors,
        warnings=warnings,
        info=info,
        content_tokens=content_tokens,
    )

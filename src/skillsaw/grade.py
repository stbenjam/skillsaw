"""
Repository quality grade.

The grade condenses a lint run into a letter (A+ .. F) suitable for a
README badge:

- **Warning/info density sets the letter.** Weighted violations
  (warnings at full weight, info lightly) are normalized per 10,000
  estimated content tokens, so a large marketplace is not penalized for
  having more surface area than a single skill. One density unit costs
  one notch (A+ -> A -> A- -> ...).
- **Errors knock off whole letters.** Errors are rare and structural —
  a broken manifest is not diluted by prose volume, so any error drops
  the grade a full letter regardless of repository size.
- Repositories smaller than one 10K-token unit are graded as one unit,
  so a tiny skill with one warning loses one notch rather than the
  whole scale.

Token estimates come from ``ContentBlock.estimate_tokens()`` (prose
blocks only); structured JSON config blocks are not content an agent
reads linearly and are excluded from the denominator.
"""

from dataclasses import dataclass, field
from typing import List, Optional

from .rule import RuleViolation, Severity

# One density unit per notch; a whole letter is three notches.
LETTER_NOTCHES = ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D", "F"]
_NOTCHES_PER_LETTER = 3

TOKENS_PER_UNIT = 10_000

# Error-count brackets -> whole letters knocked off.
_ERROR_BRACKETS = ((25, 3), (5, 2), (1, 1))

# shields.io named colors per letter.
_LETTER_COLORS = {
    "A": "brightgreen",
    "B": "green",
    "C": "yellow",
    "D": "orange",
    "F": "red",
}


@dataclass
class GradeSettings:
    """Tunable grade parameters (``grade:`` section of .skillsaw.yaml)."""

    warning_weight: float = 1.0
    info_weight: float = 0.1
    label: str = "skillsaw"

    @classmethod
    def from_dict(cls, data: dict) -> "GradeSettings":
        if not isinstance(data, dict):
            raise ValueError(f"'grade' must be a mapping, got {type(data).__name__}")
        settings = cls()
        for yaml_key, attr in (
            ("warning-weight", "warning_weight"),
            ("info-weight", "info_weight"),
        ):
            if yaml_key in data:
                value = data[yaml_key]
                if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                    raise ValueError(f"'grade.{yaml_key}' must be a non-negative number")
                setattr(settings, attr, float(value))
        if "label" in data:
            if not isinstance(data["label"], str) or not data["label"].strip():
                raise ValueError("'grade.label' must be a non-empty string")
            settings.label = data["label"].strip()
        return settings


@dataclass
class Grade:
    letter: str
    density: float
    errors: int
    warnings: int
    info: int
    content_tokens: int
    settings: GradeSettings = field(default_factory=GradeSettings)

    @property
    def color(self) -> str:
        return _LETTER_COLORS[self.letter[0]]

    def to_dict(self) -> dict:
        return {
            "letter": self.letter,
            "density": round(self.density, 2),
            "content_tokens": self.content_tokens,
        }

    def badge_json(self, version: str) -> dict:
        """shields.io endpoint-schema payload, with extra fields for
        dynamic-json badges (query ``$.message`` or ``$.grade``)."""
        return {
            "schemaVersion": 1,
            "label": self.settings.label,
            "message": self.letter,
            "color": self.color,
            "grade": self.letter,
            "density": round(self.density, 2),
            "errors": self.errors,
            "warnings": self.warnings,
            "info": self.info,
            "contentTokens": self.content_tokens,
            "skillsawVersion": version,
        }


def _error_letters(errors: int) -> int:
    for threshold, letters in _ERROR_BRACKETS:
        if errors >= threshold:
            return letters
    return 0


def compute_grade(
    violations: List[RuleViolation],
    content_tokens: int,
    settings: Optional[GradeSettings] = None,
) -> Grade:
    """Grade a lint run. ``content_tokens`` is the summed token estimate
    of every ContentBlock in the lint tree(s)."""
    settings = settings or GradeSettings()

    errors = sum(1 for v in violations if v.severity == Severity.ERROR)
    warnings = sum(1 for v in violations if v.severity == Severity.WARNING)
    info = sum(1 for v in violations if v.severity == Severity.INFO)

    units = max(content_tokens / TOKENS_PER_UNIT, 1.0)
    density = (settings.warning_weight * warnings + settings.info_weight * info) / units

    last = len(LETTER_NOTCHES) - 1
    notch = min(int(density), last)
    notch = min(notch + _NOTCHES_PER_LETTER * _error_letters(errors), last)

    return Grade(
        letter=LETTER_NOTCHES[notch],
        density=density,
        errors=errors,
        warnings=warnings,
        info=info,
        content_tokens=content_tokens,
        settings=settings,
    )

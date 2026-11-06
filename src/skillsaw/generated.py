"""Evidence retained for a verified generator copy in the lint tree."""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from skillsaw.lint_target import LintTarget


@dataclass(frozen=True)
class GeneratedCopy:
    generator: str
    sources: Tuple[Path, ...]


def generator_copy_paths(tree: "LintTarget") -> Dict[Path, GeneratedCopy]:
    """Share verified file ownership across every parser view of that file."""
    copies = tree.__dict__.get("_generator_copy_paths")
    if copies is None:
        copies = {n.resolved_path: n.generated_copy for n in tree.walk() if n.generated_copy}
        tree.__dict__["_generator_copy_paths"] = copies
    return copies


# Output size, references, policy and security have independent meaning after
# generation. Only these editorial findings can be duplicates of the source.
# A new rule stays on by default here, even if its name starts with content-.
EDITORIAL_COPY_RULES = frozenset(
    {
        "content-cognitive-chunks",
        "content-description-routing",
        "content-emphasis-density",
        "content-hook-candidate",
        "content-inconsistent-terminology",
        "content-instruction-drift",
        "content-negative-only",
        "content-progressive-disclosure",
        "content-repeated-directive",
        "content-tautological",
        "content-weak-language",
    }
)

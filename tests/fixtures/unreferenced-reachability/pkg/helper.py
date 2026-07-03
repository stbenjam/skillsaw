"""Workbook recalculation helpers.

Output is validated against the bundled data/schema.xsd before the
workbook is rewritten.
"""


def recalc(path: str) -> int:
    """Recalculate every formula cell in the workbook at *path*."""
    # Placeholder implementation for the fixture: a real skill would
    # evaluate formulas here and validate against the schema.
    with open(path, "rb") as handle:
        handle.read(1)
    return 0

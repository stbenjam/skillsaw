#!/usr/bin/env python3
"""Recalculate formula cells in a report workbook."""

import sys

from pkg.helper import recalc


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: main.py <workbook>", file=sys.stderr)
        return 2
    updated = recalc(sys.argv[1])
    print(f"updated {updated} cells")
    return 0


if __name__ == "__main__":
    sys.exit(main())

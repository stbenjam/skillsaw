#!/usr/bin/env python3
"""Build the quarterly revenue report from an exported ledger CSV."""

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path


def load(ledger):
    with ledger.open(newline="") as handle:
        yield from csv.DictReader(handle)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--segments", action="store_true")
    args = parser.parse_args(argv)

    totals = Counter()
    for row in load(args.ledger):
        totals[row["segment"] if args.segments else "all"] += int(row["cents"])

    lines = ["# Quarterly revenue", ""]
    for key, cents in sorted(totals.items()):
        lines.append(f"- {key}: ${cents / 100:,.2f}")
        print(f"{key}\t{cents}")
    args.out.write_text("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

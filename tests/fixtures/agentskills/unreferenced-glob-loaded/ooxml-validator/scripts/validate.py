#!/usr/bin/env python3
"""Validate an unpacked Office document and render an HTML report."""

import argparse
import sys
from pathlib import Path

from validators.base import BaseValidator

HERE = Path(__file__).parent

# Report shells are picked up as a set: adding a new one needs no
# change here.
SHELLS = sorted(HERE.glob("reports/*.j2"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("unpacked", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)

    validator = BaseValidator(args.unpacked, strict=args.strict)
    failures = validator.run()
    if args.report:
        args.report.write_text(validator.render(failures, SHELLS))
    for failure in failures:
        print(failure)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

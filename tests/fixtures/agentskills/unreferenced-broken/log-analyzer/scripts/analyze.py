"""Group log lines into error clusters and emit a JSON summary."""

import argparse
import json
import re
import sys
from collections import Counter

ERROR_RE = re.compile(r"\b(ERROR|FATAL)\b\s+(?P<msg>.*)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Cluster errors in a log file")
    parser.add_argument("--input", required=True)
    parser.add_argument("--format", choices=["json", "text"], default="text")
    args = parser.parse_args()

    counts: Counter = Counter()
    with open(args.input, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            match = ERROR_RE.search(line)
            if match:
                counts[match.group("msg").strip()[:120]] += 1

    if args.format == "json":
        json.dump(counts.most_common(20), sys.stdout, indent=2)
    else:
        for msg, count in counts.most_common(20):
            print(f"{count:6d}  {msg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

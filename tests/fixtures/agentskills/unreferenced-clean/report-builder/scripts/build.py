"""Collect git history and issue updates into an HTML report."""

import argparse
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a weekly status report")
    parser.add_argument("--since", default="1 week ago")
    parser.add_argument("--output", default="report.html")
    args = parser.parse_args()

    log = subprocess.run(
        ["git", "log", f"--since={args.since}", "--pretty=format:%h %s"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    items = "\n".join(f"<li>{line}</li>" for line in log.splitlines())
    template = Path(__file__).resolve().parent.parent / "assets" / "shell.html"
    html = template.read_text(encoding="utf-8").replace("{{ITEMS}}", items)
    Path(args.output).write_text(html, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

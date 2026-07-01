"""CLI for the example plugin.

Installed as the ``skillsaw-example`` console script, which skillsaw
dispatches to as ``skillsaw example [args...]`` (registered plugins only).
The script owns its own argument parsing; arguments after ``skillsaw
example`` arrive verbatim in ``sys.argv[1:]``, and this process's exit code
becomes skillsaw's exit code.
"""

import argparse
import sys

from . import SKILLSAW_RULES


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="skillsaw example",
        description="Companion commands for the example plugin",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("rules", help="List the rules this plugin provides")

    args = parser.parse_args()
    if args.command == "rules":
        for rule_class in SKILLSAW_RULES:
            rule = rule_class()
            print(f"{rule.rule_id} — {rule.description}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

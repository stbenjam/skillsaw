#!/usr/bin/env python3
"""Map changed source files to the builtin rule ids they affect.

Reads repo-relative changed file paths (one per line) on stdin and prints one
rule id per line. A rule is affected when its own module changed, or when a
non-rule Python file in the same builtin package changed (shared helpers like
``_helpers.py`` or ``__init__.py`` affect every rule in their package).

Only files under ``src/skillsaw/rules/builtin/`` are considered — changes to
core modules (lint tree, utils, CLI) are intentionally out of scope: they
affect every rule, and "run everything against real repos" is what a release
is for, not a PR comment.

Must run with the PR head's skillsaw installed, so the registry includes
rules the PR adds.
"""

import inspect
import sys
from pathlib import PurePosixPath

from skillsaw.rules.builtin import BUILTIN_RULES

BUILTIN_PREFIX = "src/skillsaw/rules/builtin/"


def module_key(rule_class):
    """Rule module path relative to the builtin package, e.g. 'agentskills/name.py'."""
    path = PurePosixPath(inspect.getfile(rule_class))
    parts = path.parts
    anchor = None
    for i in range(len(parts) - 1, -1, -1):
        if parts[i] == "builtin" and i >= 2 and parts[i - 2 : i] == ("skillsaw", "rules"):
            anchor = i
            break
    if anchor is None:
        return None
    return "/".join(parts[anchor + 1 :])


def main():
    changed = [
        line.strip()[len(BUILTIN_PREFIX) :]
        for line in sys.stdin
        if line.strip().startswith(BUILTIN_PREFIX) and line.strip().endswith(".py")
    ]
    if not changed:
        return

    rule_modules = {}
    for rule_class in BUILTIN_RULES:
        key = module_key(rule_class)
        if key:
            rule_modules.setdefault(key, []).append(rule_class)

    affected = set()
    for changed_path in changed:
        if changed_path in rule_modules:
            for rule_class in rule_modules[changed_path]:
                affected.add(rule_class().rule_id)
            continue
        # Shared module: affects every rule in the same package directory.
        package = str(PurePosixPath(changed_path).parent)
        for key, rule_classes in rule_modules.items():
            if str(PurePosixPath(key).parent) == package:
                for rule_class in rule_classes:
                    affected.add(rule_class().rule_id)

    for rule_id in sorted(affected):
        print(rule_id)


if __name__ == "__main__":
    main()

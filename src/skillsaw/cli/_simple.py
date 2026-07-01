"""Trivial subcommand handlers that need no config discovery."""

from __future__ import annotations

import sys
from pathlib import Path

from ..config import LinterConfig


def _run_init(args):
    config_path = args.path / ".skillsaw.yaml"
    if config_path.exists():
        print(f"Config file already exists: {config_path}")
        sys.exit(1)

    config = LinterConfig.for_init()
    config.save(config_path)
    print(f"Created default config: {config_path}")
    print("Run `skillsaw baseline` to accept existing violations.")
    sys.exit(0)


def _run_list_rules():
    from ..rules.builtin import BUILTIN_RULES

    print("Available builtin rules:\n")
    for rule_class in BUILTIN_RULES:
        rule = rule_class()
        fix_label = "auto" if rule.supports_autofix else "none"
        print(f"  {rule.rule_id}")
        print(f"    {rule.description}")
        print(f"    Default severity: {rule.default_severity().value}")
        print(f"    Autofix: {fix_label}")
        print()
    sys.exit(0)

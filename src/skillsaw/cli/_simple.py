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


def _print_rule_entry(rule):
    fix_types = []
    if rule.supports_autofix:
        fix_types.append("auto")
    if rule.llm_fix_prompt is not None:
        fix_types.append("llm")
    fix_label = ", ".join(fix_types) if fix_types else "none"
    print(f"  {rule.rule_id}")
    print(f"    {rule.description}")
    print(f"    Default severity: {rule.default_severity().value}")
    print(f"    Autofix: {fix_label}")
    print()


def _run_list_rules():
    from ..plugins import load_plugins
    from ..rules.builtin import BUILTIN_RULES

    print("Available builtin rules:\n")
    for rule_class in BUILTIN_RULES:
        _print_rule_entry(rule_class())

    for plugin in load_plugins():
        if plugin.error:
            print(f"Plugin {plugin.name} failed to load: {plugin.error}\n")
            continue
        print(f"Rules from plugin {plugin.name}:\n")
        for rule_class in plugin.rule_classes:
            try:
                _print_rule_entry(rule_class())
            except Exception as e:
                print(f"  {rule_class.__name__}: failed to instantiate ({e})\n")
    sys.exit(0)


def _run_plugins():
    from ..plugins import load_plugins

    plugins = load_plugins()
    if not plugins:
        print("No skillsaw plugins installed.")
        print()
        print("Plugins are Python packages that add lint rules; install one with")
        print("pip (e.g. `pip install skillsaw-<name>`) and it is picked up")
        print("automatically. See https://skillsaw.org/plugins/ to write your own.")
        sys.exit(0)

    had_errors = False
    print("Installed skillsaw plugins:\n")
    for plugin in plugins:
        dist = ""
        if plugin.distribution:
            version = f" {plugin.version}" if plugin.version else ""
            dist = f" ({plugin.distribution}{version})"
        print(f"  {plugin.name}{dist}")
        print(f"    source: {plugin.source}")
        if plugin.error:
            had_errors = True
            print(f"    ERROR: {plugin.error}")
        elif not plugin.rule_classes:
            print("    rules: (none)")
        else:
            print("    rules:")
            for rule_class in plugin.rule_classes:
                try:
                    rule = rule_class()
                    print(f"      {rule.rule_id} — {rule.description}")
                except Exception as e:
                    had_errors = True
                    print(f"      {rule_class.__name__}: failed to instantiate ({e})")
        print()

    print("Disable a plugin with `plugins: {disable: [<name>]}` in .skillsaw.yaml,")
    print("or skip all plugins for one run with `skillsaw lint --no-plugins`.")
    sys.exit(1 if had_errors else 0)

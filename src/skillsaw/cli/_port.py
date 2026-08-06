"""Handler for the ``skillsaw port`` subcommand."""

from __future__ import annotations

import sys
from pathlib import Path

from ..config import LinterConfig
from ..context import RepositoryContext
from ..linter import Linter
from ..paths import safe_resolve
from ..port import apply_plan, plan_port
from ._config import _get_version, load_config
from ._helpers import _ansi_colors, color_enabled


class _PortProgress:
    """Single-line conversion progress on stderr for interactive runs."""

    def __init__(self, args) -> None:
        self.enabled = sys.stderr.isatty() and not getattr(args, "no_progress", False)

    def __call__(self, index: int, total: int, name: str) -> None:
        if self.enabled:
            sys.stderr.write(f"\r\x1b[K  converting [{index}/{total}] {name}")
            sys.stderr.flush()

    def clear(self) -> None:
        if self.enabled:
            sys.stderr.write("\r\x1b[K")
            sys.stderr.flush()


def _port_targets(path: Path, config: LinterConfig) -> list:
    """Every plugin directory under *path*, or *path* itself as one package.

    Reuses lint discovery so a marketplace ports every plugin it contains
    and a single-plugin repo ports its root — same shape ``lint`` sees.
    """
    context = RepositoryContext(
        path,
        exclude_patterns=config.exclude_patterns,
        content_paths=config.content_paths,
    )
    targets = context.distinct_plugin_dirs()
    return targets or [path]


def _run_port(args):
    if args.target != "agent-plugin":
        print(
            f"Error: unknown port target '{args.target}' (available: agent-plugin)", file=sys.stderr
        )
        sys.exit(1)
    if not args.path.exists():
        print(f"Error: Path not found: {args.path}", file=sys.stderr)
        sys.exit(1)

    config, _config_path = load_config(args, args.path)
    c = _ansi_colors(color_enabled(sys.stdout, args.color))
    base = safe_resolve(args.path) or args.path

    print(f"skillsaw {_get_version()}")
    print(f"Porting to Agent Plugins v1: {base}\n")

    def _rel(root: Path) -> Path:
        resolved = safe_resolve(root) or root
        try:
            return resolved.relative_to(base) if resolved != base else Path(".")
        except ValueError:
            return resolved

    targets = _port_targets(args.path, config)
    progress = _PortProgress(args)
    verify_rules = {"agent-plugin-json-valid", "agent-plugin-mcp-valid"}

    ported = []
    skipped = []
    note_count = 0
    file_counts = {"plugin.json": 0, "mcp.json": 0}
    verify_failures = []

    try:
        for index, target in enumerate(targets, 1):
            rel = _rel(target)
            progress(index, len(targets), str(rel))
            plan = plan_port(target)
            progress.clear()

            if plan.skipped:
                skipped.append(plan)
                print(f"  {c['dim']}- [{rel}] {plan.skipped}{c['reset']}")
                continue
            if not plan.writes:
                continue

            source = "+".join(plan.sources)
            files = ", ".join(plan.writes)
            print(f"  {c['green']}✓{c['reset']} {c['bold']}[{rel}]{c['reset']} {source} → {files}")
            for note in plan.notes:
                note_count += 1
                print(f"      {c['yellow']}note:{c['reset']} {note}")
            if args.dry_run:
                for filename, content in plan.writes.items():
                    print(f"{c['dim']}--- {rel}/{filename} ---{c['reset']}")
                    print(content, end="")

            ported.append(plan)
            for filename in plan.writes:
                file_counts[filename] = file_counts.get(filename, 0) + 1

            if args.dry_run:
                continue

            apply_plan(plan)
            # A port isn't done until the target format's own rules accept
            # it. Config advisories (e.g. deprecation notices) belong to
            # lint runs; only the format's own findings gate the port.
            context = RepositoryContext(target, exclude_patterns=config.exclude_patterns)
            linter = Linter(
                context,
                config,
                rule_ids=verify_rules,
                no_plugins=True,
                no_custom_rules=True,
            )
            for violation in linter.run():
                if violation.rule_id in verify_rules:
                    verify_failures.append(violation)
                    print(f"  {violation}")
    finally:
        progress.clear()

    if not ported:
        print("\nNothing to port.")
        # A rerun over an already-ported tree is success. Refusing to
        # overwrite a foreign plugin.json, or finding nothing portable at
        # all, is not.
        conflicts = any("refusing to overwrite" in p.skipped for p in skipped)
        already = any("already an Agent Plugins package" in p.skipped for p in skipped)
        sys.exit(0 if already and not conflicts else 1)

    counts = ", ".join(f"{n} {name}" for name, n in file_counts.items() if n)
    plugin_word = "plugin" if len(ported) == 1 else "plugins"
    print("\nSummary:")
    print(f"  Ported:     {len(ported)} {plugin_word} ({counts})")
    if skipped:
        print(f"  Skipped:    {len(skipped)}")
    if note_count:
        print(f"  Notes:      {note_count} (shown above)")

    if args.dry_run:
        print(f"\n{c['yellow']}dry-run — no files were written{c['reset']}")
        sys.exit(0)

    if verify_failures:
        print(f"  Validation: {c['red']}✗ {len(verify_failures)} violation(s){c['reset']}")
        print(
            f"\n{c['red']}✗{c['reset']} Ported {len(ported)} {plugin_word}; fix the violations above."
        )
        sys.exit(1)

    print(f"  Validation: {c['green']}✓ passed{c['reset']}")
    print(f"\n{c['green']}✓{c['reset']} Converted {len(ported)} {plugin_word} to Agent Plugins v1")
    sys.exit(0)

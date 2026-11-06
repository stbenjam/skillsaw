"""Optional checks for literal repository-local Pi resource declarations."""

import os
from pathlib import Path
from typing import List

from skillsaw.blocks.pi import PiPackageBlock, PiSettingsBlock
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.diagnostics import safe_display
from skillsaw.paths import contained_resolve, is_absolute_path, safe_exists, safe_is_file
from skillsaw.discovery.pi import local_path
from skillsaw.formats.pi import RESOURCE_FIELDS, REMOTE_PREFIXES, settings_resources, string_list
from skillsaw.rule import Rule, RuleViolation, Severity


class PiResourcePathsRule(Rule):
    """Find missing local paths when linting a fully assembled Pi package."""

    since = "0.21.0"
    default_enabled = False
    repo_types = frozenset({RepositoryType.PI, RepositoryType.PI_PACKAGE})

    @property
    def rule_id(self) -> str:
        return "pi-resource-paths"

    @property
    def description(self) -> str:
        return "Literal Pi resource paths should exist in the assembled checkout"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        for cls in (PiPackageBlock, PiSettingsBlock):
            for block in context.lint_tree.find(cls):
                data = block.raw_data
                if not isinstance(data, dict) or block.parse_error:
                    continue
                settings = isinstance(block, PiSettingsBlock)
                config = settings_resources(data) if settings else data.get("pi")
                if not isinstance(config, dict):
                    continue
                entries = [
                    (key, entry)
                    for key in RESOURCE_FIELDS
                    if string_list(config.get(key))
                    for entry in config[key]
                ]
                if settings and isinstance(config.get("packages"), list):
                    for item in config["packages"]:
                        source = item.get("source") if isinstance(item, dict) else item
                        if isinstance(source, str):
                            entries.append(("packages", source))
                missing = []
                for key, entry in entries:
                    if entry.startswith(("!", "+", "-", "~", *REMOTE_PREFIXES)) or any(
                        c in entry for c in "*?${}"
                    ):
                        continue
                    path = local_path(
                        block.path.parent, entry, context.root_path, settings=settings
                    )
                    if (
                        path is not None
                        and not context.is_path_excluded(path)
                        and not safe_exists(path)
                    ):
                        missing.append(f"{key}: {safe_display(entry)!r}")
                # Pi 1.5.0 shows a package changelog only from a file inside
                # the package; an empty string turns the changelog off.
                changelog = None if settings else config.get("changelogPath")
                if isinstance(changelog, str) and changelog:
                    root = context.resolve_path(block.path.parent)
                    # Pi applies Node's lexical path.resolve before touching the disk.
                    target = Path(os.path.abspath(block.path.parent / changelog))
                    shown = f"changelogPath: {safe_display(changelog)!r}"
                    # An absolute path, in either platform's spelling, cannot
                    # follow the package to wherever Pi installs it.
                    if (
                        root is None
                        or is_absolute_path(changelog)
                        or contained_resolve(target, root, context.resolve_path) in (None, root)
                    ):
                        missing.append(f"{shown} (outside the package)")
                    elif not context.is_path_excluded(target) and not safe_is_file(target):
                        missing.append(shown)
                if missing:
                    violations.append(
                        self.violation(
                            "Missing local Pi resources: "
                            + "; ".join(missing[:5])
                            + ". Paths are relative to this file; build or install bundled resources before checking, or configure rule exclusions.",
                            block=block,
                        )
                    )
        return violations

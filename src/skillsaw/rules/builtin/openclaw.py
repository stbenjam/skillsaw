"""
Rules for validating openclaw metadata in SKILL.md frontmatter
"""

import re
from pathlib import Path
from typing import Dict, List, Optional

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.rules.builtin.agentskills import _parse_skill_md


def _build_frontmatter_line_map(skill_md: Path) -> Dict[str, int]:
    """Map YAML key names to their line numbers in SKILL.md frontmatter."""
    result: Dict[str, int] = {}
    try:
        lines = skill_md.read_text().splitlines()
    except IOError:
        return result
    in_frontmatter = False
    for i, line in enumerate(lines, start=1):
        if i == 1 and line.strip() == "---":
            in_frontmatter = True
            continue
        if in_frontmatter and line.strip() == "---":
            break
        if not in_frontmatter:
            continue
        m = re.match(r"^(\s*)-\s+(\w[\w-]*):", line)
        if m:
            result[m.group(2)] = i
            continue
        m = re.match(r"^(\s*)(\w[\w-]*):", line)
        if m:
            result[m.group(2)] = i
    return result


VALID_OS_VALUES = {"darwin", "linux", "win32"}
VALID_INSTALL_KINDS = {"brew", "node", "go", "uv", "download"}
VALID_ARCHIVE_TYPES = {"tar.gz", "tar.bz2", "zip"}


class OpenclawMetadataRule(Rule):
    """Validate metadata.openclaw in SKILL.md frontmatter against the openclaw spec"""

    repo_types = {
        RepositoryType.AGENTSKILLS,
        RepositoryType.SINGLE_PLUGIN,
        RepositoryType.MARKETPLACE,
        RepositoryType.DOT_CLAUDE,
    }

    @property
    def rule_id(self) -> str:
        return "openclaw-metadata"

    @property
    def description(self) -> str:
        return "Validate metadata.openclaw fields against the openclaw spec"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        for skill_path in context.skills:
            skill_md = skill_path / "SKILL.md"
            frontmatter, error = _parse_skill_md(skill_path)

            if error or not frontmatter:
                continue

            metadata = frontmatter.get("metadata")
            if not isinstance(metadata, dict):
                continue

            openclaw = metadata.get("openclaw")
            if openclaw is None:
                continue

            line_map = _build_frontmatter_line_map(skill_md)

            if not isinstance(openclaw, dict):
                violations.append(
                    self.violation(
                        "'metadata.openclaw' must be a mapping",
                        file_path=skill_md,
                        line=line_map.get("openclaw"),
                    )
                )
                continue

            self._check_top_level(openclaw, skill_md, line_map, violations)
            self._check_requires(openclaw, skill_md, line_map, violations)
            self._check_install(openclaw, skill_md, line_map, violations)

        return violations

    def _check_top_level(self, openclaw, skill_md, line_map, violations):
        if "always" in openclaw and not isinstance(openclaw["always"], bool):
            violations.append(
                self.violation(
                    "'metadata.openclaw.always' must be a boolean",
                    file_path=skill_md,
                    line=line_map.get("always"),
                )
            )

        if "emoji" in openclaw and not isinstance(openclaw["emoji"], str):
            violations.append(
                self.violation(
                    "'metadata.openclaw.emoji' must be a string",
                    file_path=skill_md,
                    line=line_map.get("emoji"),
                )
            )

        if "homepage" in openclaw:
            hp = openclaw["homepage"]
            if not isinstance(hp, str):
                violations.append(
                    self.violation(
                        "'metadata.openclaw.homepage' must be a string",
                        file_path=skill_md,
                        line=line_map.get("homepage"),
                    )
                )

        if "primaryEnv" in openclaw and not isinstance(openclaw["primaryEnv"], str):
            violations.append(
                self.violation(
                    "'metadata.openclaw.primaryEnv' must be a string",
                    file_path=skill_md,
                    line=line_map.get("primaryEnv"),
                )
            )

        if "os" in openclaw:
            os_line = line_map.get("os")
            os_val = openclaw["os"]
            if not isinstance(os_val, list):
                violations.append(
                    self.violation(
                        "'metadata.openclaw.os' must be a list of strings",
                        file_path=skill_md,
                        line=os_line,
                    )
                )
            elif not all(isinstance(v, str) for v in os_val):
                violations.append(
                    self.violation(
                        "'metadata.openclaw.os' items must be strings",
                        file_path=skill_md,
                        line=os_line,
                    )
                )
            else:
                invalid = [v for v in os_val if v not in VALID_OS_VALUES]
                if invalid:
                    violations.append(
                        self.violation(
                            f"'metadata.openclaw.os' contains invalid values: {invalid} "
                            f"(allowed: {sorted(VALID_OS_VALUES)})",
                            file_path=skill_md,
                            line=os_line,
                        )
                    )

    def _check_requires(self, openclaw, skill_md, line_map, violations):
        requires = openclaw.get("requires")
        if requires is None:
            return

        if not isinstance(requires, dict):
            violations.append(
                self.violation(
                    "'metadata.openclaw.requires' must be a mapping",
                    file_path=skill_md,
                    line=line_map.get("requires"),
                )
            )
            return

        for field in ("bins", "anyBins", "env", "config"):
            if field in requires:
                val = requires[field]
                if not isinstance(val, list):
                    violations.append(
                        self.violation(
                            f"'metadata.openclaw.requires.{field}' must be a list",
                            file_path=skill_md,
                            line=line_map.get(field),
                        )
                    )
                elif not all(isinstance(v, str) for v in val):
                    violations.append(
                        self.violation(
                            f"'metadata.openclaw.requires.{field}' items must be strings",
                            file_path=skill_md,
                            line=line_map.get(field),
                        )
                    )

    def _check_install(self, openclaw, skill_md, line_map, violations):
        install = openclaw.get("install")
        if install is None:
            return

        install_line = line_map.get("install")
        if not isinstance(install, list):
            violations.append(
                self.violation(
                    "'metadata.openclaw.install' must be a list",
                    file_path=skill_md,
                    line=install_line,
                )
            )
            return

        for i, entry in enumerate(install):
            if not isinstance(entry, dict):
                violations.append(
                    self.violation(
                        f"'metadata.openclaw.install[{i}]' must be a mapping",
                        file_path=skill_md,
                        line=install_line,
                    )
                )
                continue

            kind = entry.get("kind")
            if kind is not None:
                if not isinstance(kind, str):
                    violations.append(
                        self.violation(
                            f"'metadata.openclaw.install[{i}].kind' must be a string",
                            file_path=skill_md,
                            line=line_map.get("kind"),
                        )
                    )
                elif kind not in VALID_INSTALL_KINDS:
                    violations.append(
                        self.violation(
                            f"'metadata.openclaw.install[{i}].kind' is '{kind}', "
                            f"expected one of: {sorted(VALID_INSTALL_KINDS)}",
                            file_path=skill_md,
                            line=line_map.get("kind"),
                        )
                    )

            if isinstance(kind, str) and kind == "download" and "url" not in entry:
                violations.append(
                    self.violation(
                        f"'metadata.openclaw.install[{i}]' with kind 'download' requires 'url'",
                        file_path=skill_md,
                        line=line_map.get("kind"),
                    )
                )

            if "os" in entry:
                os_val = entry["os"]
                os_line = line_map.get("os")
                if not isinstance(os_val, list):
                    violations.append(
                        self.violation(
                            f"'metadata.openclaw.install[{i}].os' must be a list",
                            file_path=skill_md,
                            line=os_line,
                        )
                    )
                elif not all(isinstance(v, str) for v in os_val):
                    violations.append(
                        self.violation(
                            f"'metadata.openclaw.install[{i}].os' items must be strings",
                            file_path=skill_md,
                            line=os_line,
                        )
                    )
                else:
                    invalid = [v for v in os_val if v not in VALID_OS_VALUES]
                    if invalid:
                        violations.append(
                            self.violation(
                                f"'metadata.openclaw.install[{i}].os' contains invalid values: "
                                f"{invalid} (allowed: {sorted(VALID_OS_VALUES)})",
                                file_path=skill_md,
                                line=os_line,
                            )
                        )

            if "archive" in entry:
                archive = entry["archive"]
                archive_line = line_map.get("archive")
                if not isinstance(archive, str):
                    violations.append(
                        self.violation(
                            f"'metadata.openclaw.install[{i}].archive' must be a string",
                            file_path=skill_md,
                            line=archive_line,
                        )
                    )
                elif archive not in VALID_ARCHIVE_TYPES:
                    violations.append(
                        self.violation(
                            f"'metadata.openclaw.install[{i}].archive' is '{archive}', "
                            f"expected one of: {sorted(VALID_ARCHIVE_TYPES)}",
                            file_path=skill_md,
                            line=archive_line,
                        )
                    )

            if "extract" in entry and not isinstance(entry["extract"], bool):
                violations.append(
                    self.violation(
                        f"'metadata.openclaw.install[{i}].extract' must be a boolean",
                        file_path=skill_md,
                        line=line_map.get("extract"),
                    )
                )

            if "stripComponents" in entry and not isinstance(
                entry["stripComponents"], (int, float)
            ):
                violations.append(
                    self.violation(
                        f"'metadata.openclaw.install[{i}].stripComponents' must be a number",
                        file_path=skill_md,
                        line=line_map.get("stripComponents"),
                    )
                )

            for str_field in ("id", "label", "formula", "url", "targetDir"):
                if str_field in entry and not isinstance(entry[str_field], str):
                    violations.append(
                        self.violation(
                            f"'metadata.openclaw.install[{i}].{str_field}' must be a string",
                            file_path=skill_md,
                            line=line_map.get(str_field),
                        )
                    )

            if "bins" in entry:
                bins = entry["bins"]
                bins_line = line_map.get("bins")
                if not isinstance(bins, list):
                    violations.append(
                        self.violation(
                            f"'metadata.openclaw.install[{i}].bins' must be a list",
                            file_path=skill_md,
                            line=bins_line,
                        )
                    )
                elif not all(isinstance(b, str) for b in bins):
                    violations.append(
                        self.violation(
                            f"'metadata.openclaw.install[{i}].bins' items must be strings",
                            file_path=skill_md,
                            line=bins_line,
                        )
                    )

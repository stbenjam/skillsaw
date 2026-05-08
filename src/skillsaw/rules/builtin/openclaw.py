"""
Rules for validating openclaw metadata in SKILL.md frontmatter
"""

from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.rules.builtin.agentskills import _parse_skill_md

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

            if not isinstance(openclaw, dict):
                violations.append(
                    self.violation(
                        "'metadata.openclaw' must be a mapping",
                        file_path=skill_md,
                    )
                )
                continue

            self._check_top_level(openclaw, skill_md, violations)
            self._check_requires(openclaw, skill_md, violations)
            self._check_install(openclaw, skill_md, violations)

        return violations

    def _check_top_level(self, openclaw, skill_md, violations):
        if "always" in openclaw and not isinstance(openclaw["always"], bool):
            violations.append(
                self.violation("'metadata.openclaw.always' must be a boolean", file_path=skill_md)
            )

        if "emoji" in openclaw and not isinstance(openclaw["emoji"], str):
            violations.append(
                self.violation("'metadata.openclaw.emoji' must be a string", file_path=skill_md)
            )

        if "homepage" in openclaw:
            hp = openclaw["homepage"]
            if not isinstance(hp, str):
                violations.append(
                    self.violation(
                        "'metadata.openclaw.homepage' must be a string", file_path=skill_md
                    )
                )

        if "primaryEnv" in openclaw and not isinstance(openclaw["primaryEnv"], str):
            violations.append(
                self.violation(
                    "'metadata.openclaw.primaryEnv' must be a string", file_path=skill_md
                )
            )

        if "os" in openclaw:
            os_val = openclaw["os"]
            if not isinstance(os_val, list):
                violations.append(
                    self.violation(
                        "'metadata.openclaw.os' must be a list of strings", file_path=skill_md
                    )
                )
            elif not all(isinstance(v, str) for v in os_val):
                violations.append(
                    self.violation(
                        "'metadata.openclaw.os' items must be strings", file_path=skill_md
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
                        )
                    )

    def _check_requires(self, openclaw, skill_md, violations):
        requires = openclaw.get("requires")
        if requires is None:
            return

        if not isinstance(requires, dict):
            violations.append(
                self.violation("'metadata.openclaw.requires' must be a mapping", file_path=skill_md)
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
                        )
                    )
                elif not all(isinstance(v, str) for v in val):
                    violations.append(
                        self.violation(
                            f"'metadata.openclaw.requires.{field}' items must be strings",
                            file_path=skill_md,
                        )
                    )

    def _check_install(self, openclaw, skill_md, violations):
        install = openclaw.get("install")
        if install is None:
            return

        if not isinstance(install, list):
            violations.append(
                self.violation("'metadata.openclaw.install' must be a list", file_path=skill_md)
            )
            return

        for i, entry in enumerate(install):
            if not isinstance(entry, dict):
                violations.append(
                    self.violation(
                        f"'metadata.openclaw.install[{i}]' must be a mapping",
                        file_path=skill_md,
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
                        )
                    )
                elif kind not in VALID_INSTALL_KINDS:
                    violations.append(
                        self.violation(
                            f"'metadata.openclaw.install[{i}].kind' is '{kind}', "
                            f"expected one of: {sorted(VALID_INSTALL_KINDS)}",
                            file_path=skill_md,
                        )
                    )

            if isinstance(kind, str) and kind == "download" and "url" not in entry:
                violations.append(
                    self.violation(
                        f"'metadata.openclaw.install[{i}]' with kind 'download' requires 'url'",
                        file_path=skill_md,
                    )
                )

            if "os" in entry:
                os_val = entry["os"]
                if not isinstance(os_val, list):
                    violations.append(
                        self.violation(
                            f"'metadata.openclaw.install[{i}].os' must be a list",
                            file_path=skill_md,
                        )
                    )
                elif not all(isinstance(v, str) for v in os_val):
                    violations.append(
                        self.violation(
                            f"'metadata.openclaw.install[{i}].os' items must be strings",
                            file_path=skill_md,
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
                            )
                        )

            if "archive" in entry:
                archive = entry["archive"]
                if not isinstance(archive, str):
                    violations.append(
                        self.violation(
                            f"'metadata.openclaw.install[{i}].archive' must be a string",
                            file_path=skill_md,
                        )
                    )
                elif archive not in VALID_ARCHIVE_TYPES:
                    violations.append(
                        self.violation(
                            f"'metadata.openclaw.install[{i}].archive' is '{archive}', "
                            f"expected one of: {sorted(VALID_ARCHIVE_TYPES)}",
                            file_path=skill_md,
                        )
                    )

            if "extract" in entry and not isinstance(entry["extract"], bool):
                violations.append(
                    self.violation(
                        f"'metadata.openclaw.install[{i}].extract' must be a boolean",
                        file_path=skill_md,
                    )
                )

            if "stripComponents" in entry and not isinstance(
                entry["stripComponents"], (int, float)
            ):
                violations.append(
                    self.violation(
                        f"'metadata.openclaw.install[{i}].stripComponents' must be a number",
                        file_path=skill_md,
                    )
                )

            for str_field in ("id", "label", "formula", "url", "targetDir"):
                if str_field in entry and not isinstance(entry[str_field], str):
                    violations.append(
                        self.violation(
                            f"'metadata.openclaw.install[{i}].{str_field}' must be a string",
                            file_path=skill_md,
                        )
                    )

            if "bins" in entry:
                bins = entry["bins"]
                if not isinstance(bins, list):
                    violations.append(
                        self.violation(
                            f"'metadata.openclaw.install[{i}].bins' must be a list",
                            file_path=skill_md,
                        )
                    )
                elif not all(isinstance(b, str) for b in bins):
                    violations.append(
                        self.violation(
                            f"'metadata.openclaw.install[{i}].bins' items must be strings",
                            file_path=skill_md,
                        )
                    )

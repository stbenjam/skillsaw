"""
Rule for validating openclaw metadata in SKILL.md frontmatter
"""

import difflib
from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.rules.builtin.content_analysis import FrontmatterField, SkillBlock

VALID_OS_VALUES = {"darwin", "linux", "win32"}
VALID_INSTALL_KINDS = {"brew", "node", "go", "uv", "download"}
VALID_ARCHIVE_TYPES = {"tar.gz", "tar.bz2", "zip"}

# Known top-level keys under metadata.openclaw (mirrors openclaw's
# OpenClawSkillMetadata in src/skills/types.ts). Used only for typo detection —
# unknown keys are silently ignored by openclaw, so we warn only on near-misses.
KNOWN_OPENCLAW_KEYS = {
    "always",
    "skillKey",
    "primaryEnv",
    "apiKey",
    "hidden",
    "emoji",
    "homepage",
    "os",
    "requires",
    "install",
}

# Field(s) that satisfy each install kind. openclaw silently DROPS an install
# entry whose kind is missing its required field (see src/skills/loading/
# frontmatter.ts), so the installer never appears. A tuple means "any one of".
REQUIRED_INSTALL_FIELDS = {
    "brew": ("formula", "cask"),
    "node": ("package",),
    "go": ("module",),
    "uv": ("package",),
    "download": ("url",),
}


class OpenclawMetadataRule(Rule):
    """Validate metadata.openclaw in SKILL.md frontmatter against the OpenClaw spec"""

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
        return "Validate metadata.openclaw fields against the OpenClaw spec"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        for block in context.lint_tree.find(SkillBlock):
            metadata_fields = [f for f in block.find(FrontmatterField) if f.name == "metadata"]
            if not metadata_fields:
                continue
            metadata = metadata_fields[0].value
            if not isinstance(metadata, dict):
                continue

            openclaw = metadata.get("openclaw")
            if openclaw is None:
                continue

            line_map = block.line_map()

            if not isinstance(openclaw, dict):
                violations.append(
                    self.violation(
                        "'metadata.openclaw' must be a mapping",
                        file_path=block.path,
                        line=line_map.get("openclaw"),
                    )
                )
                continue

            self._check_top_level(openclaw, block.path, line_map, violations)
            self._check_requires(openclaw, block.path, line_map, violations)
            self._check_install(openclaw, block.path, line_map, violations)

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

        for str_field in ("skillKey", "primaryEnv", "apiKey"):
            if str_field in openclaw and not isinstance(openclaw[str_field], str):
                violations.append(
                    self.violation(
                        f"'metadata.openclaw.{str_field}' must be a string",
                        file_path=skill_md,
                        line=line_map.get(str_field),
                    )
                )

        if "hidden" in openclaw and not isinstance(openclaw["hidden"], bool):
            violations.append(
                self.violation(
                    "'metadata.openclaw.hidden' must be a boolean",
                    file_path=skill_md,
                    line=line_map.get("hidden"),
                )
            )

        # openclaw silently ignores unrecognized keys, so a typo like `require`
        # or `installs` vanishes without error. Warn only on near-misses to a
        # known key (deliberate free-form keys stay unflagged).
        for key in openclaw:
            if key in KNOWN_OPENCLAW_KEYS:
                continue
            match = difflib.get_close_matches(key, KNOWN_OPENCLAW_KEYS, n=1, cutoff=0.8)
            if match:
                violations.append(
                    self.violation(
                        f"'metadata.openclaw.{key}' is not a recognized key "
                        f"(did you mean '{match[0]}'?)",
                        file_path=skill_md,
                        line=line_map.get(key),
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

            # openclaw reads `kind`, falling back to `type` as an alias, and
            # lowercases it before matching (see parseOpenClawManifestInstallBase).
            kind_field = "kind" if "kind" in entry else ("type" if "type" in entry else None)
            raw_kind = entry.get("kind", entry.get("type"))
            effective_kind = None
            if raw_kind is not None:
                if not isinstance(raw_kind, str):
                    violations.append(
                        self.violation(
                            f"'metadata.openclaw.install[{i}].{kind_field}' must be a string",
                            file_path=skill_md,
                            line=line_map.get(kind_field),
                        )
                    )
                else:
                    normalized = raw_kind.strip().lower()
                    if normalized in VALID_INSTALL_KINDS:
                        effective_kind = normalized
                    else:
                        violations.append(
                            self.violation(
                                f"'metadata.openclaw.install[{i}].{kind_field}' is '{raw_kind}', "
                                f"expected one of: {sorted(VALID_INSTALL_KINDS)}",
                                file_path=skill_md,
                                line=line_map.get(kind_field),
                            )
                        )

            # openclaw drops entries whose kind is missing its required field,
            # so the installer silently never appears.
            if effective_kind in REQUIRED_INSTALL_FIELDS:
                required = REQUIRED_INSTALL_FIELDS[effective_kind]
                if not any(field in entry for field in required):
                    needed = " or ".join(f"'{field}'" for field in required)
                    violations.append(
                        self.violation(
                            f"'metadata.openclaw.install[{i}]' with kind "
                            f"'{effective_kind}' requires {needed}",
                            file_path=skill_md,
                            line=line_map.get(kind_field),
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

            for str_field in (
                "id",
                "label",
                "formula",
                "cask",
                "package",
                "module",
                "url",
                "targetDir",
            ):
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

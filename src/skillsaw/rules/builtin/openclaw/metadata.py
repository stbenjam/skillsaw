"""
Rule for validating openclaw metadata in SKILL.md frontmatter
"""

import difflib
from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.rules.builtin.content_analysis import FrontmatterField, SkillBlock
from skillsaw.utils import yaml_path_line_lookup

VALID_OS_VALUES = {"darwin", "linux", "win32"}
VALID_INSTALL_KINDS = {"brew", "node", "go", "uv", "download"}
VALID_ARCHIVE_TYPES = {"tar.gz", "tar.bz2", "zip"}

# Known top-level keys under metadata.openclaw from OpenClaw and ClawHub. Used
# only for typo detection — unknown keys are silently ignored by openclaw, so
# we warn only on near-misses.
KNOWN_OPENCLAW_KEYS = (
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
    "category",
    "cliHelp",
)

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

            # Exact dotted-path lookups (parsed once per block).  The flat
            # block.line_map() is last-occurrence-wins across the whole
            # frontmatter, which misattributes lines whenever the same key
            # name repeats (e.g. `kind` in several install entries, or `os`
            # both top-level and inside an entry).
            node_line = yaml_path_line_lookup(block.read_frontmatter_text(), line_offset=1)

            if not isinstance(openclaw, dict):
                violations.append(
                    self.violation(
                        "'metadata.openclaw' must be a mapping",
                        file_path=block.path,
                        line=node_line("metadata.openclaw"),
                    )
                )
                continue

            self._check_top_level(openclaw, block.path, node_line, violations, block.line_map())
            self._check_requires(openclaw, block.path, node_line, violations)
            self._check_install(openclaw, block.path, node_line, violations)

        return violations

    def _check_top_level(self, openclaw, skill_md, node_line, violations, flat_line_map):
        if "always" in openclaw and not isinstance(openclaw["always"], bool):
            violations.append(
                self.violation(
                    "'metadata.openclaw.always' must be a boolean",
                    file_path=skill_md,
                    line=node_line("metadata.openclaw.always"),
                )
            )

        if "emoji" in openclaw and not isinstance(openclaw["emoji"], str):
            violations.append(
                self.violation(
                    "'metadata.openclaw.emoji' must be a string",
                    file_path=skill_md,
                    line=node_line("metadata.openclaw.emoji"),
                )
            )

        if "homepage" in openclaw:
            hp = openclaw["homepage"]
            if not isinstance(hp, str):
                violations.append(
                    self.violation(
                        "'metadata.openclaw.homepage' must be a string",
                        file_path=skill_md,
                        line=node_line("metadata.openclaw.homepage"),
                    )
                )

        if "primaryEnv" in openclaw and not isinstance(openclaw["primaryEnv"], str):
            violations.append(
                self.violation(
                    "'metadata.openclaw.primaryEnv' must be a string",
                    file_path=skill_md,
                    line=node_line("metadata.openclaw.primaryEnv"),
                )
            )

        if "os" in openclaw:
            os_line = node_line("metadata.openclaw.os")
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

        for str_field in ("skillKey", "apiKey"):
            if str_field in openclaw and not isinstance(openclaw[str_field], str):
                violations.append(
                    self.violation(
                        f"'metadata.openclaw.{str_field}' must be a string",
                        file_path=skill_md,
                        line=node_line(f"metadata.openclaw.{str_field}"),
                    )
                )

        if "hidden" in openclaw and not isinstance(openclaw["hidden"], bool):
            violations.append(
                self.violation(
                    "'metadata.openclaw.hidden' must be a boolean",
                    file_path=skill_md,
                    line=node_line("metadata.openclaw.hidden"),
                )
            )

        # openclaw silently ignores unrecognized keys, so a typo like `require`
        # or `installs` vanishes without error. Warn only on near-misses to a
        # known key (deliberate free-form keys stay unflagged).
        for key in openclaw:
            if not isinstance(key, str):
                continue
            if key in KNOWN_OPENCLAW_KEYS:
                continue
            match = difflib.get_close_matches(key, KNOWN_OPENCLAW_KEYS, n=1, cutoff=0.8)
            if match:
                # Keys containing path syntax ('.' or '[') cannot be expressed
                # as a dotted path — fall back to the flat line map, which is
                # accurate for a key name that appears once.
                if "." not in key and "[" not in key:
                    key_line = node_line(f"metadata.openclaw.{key}")
                else:
                    key_line = flat_line_map.get(key)
                violations.append(
                    self.violation(
                        f"'metadata.openclaw.{key}' is not a recognized key "
                        f"(did you mean '{match[0]}'?)",
                        file_path=skill_md,
                        line=key_line,
                    )
                )

    def _check_requires(self, openclaw, skill_md, node_line, violations):
        requires = openclaw.get("requires")
        if requires is None:
            return

        if not isinstance(requires, dict):
            violations.append(
                self.violation(
                    "'metadata.openclaw.requires' must be a mapping",
                    file_path=skill_md,
                    line=node_line("metadata.openclaw.requires"),
                )
            )
            return

        for field in ("bins", "anyBins", "env", "config"):
            if field in requires:
                val = requires[field]
                field_line = node_line(f"metadata.openclaw.requires.{field}")
                if not isinstance(val, list):
                    violations.append(
                        self.violation(
                            f"'metadata.openclaw.requires.{field}' must be a list",
                            file_path=skill_md,
                            line=field_line,
                        )
                    )
                elif not all(isinstance(v, str) for v in val):
                    violations.append(
                        self.violation(
                            f"'metadata.openclaw.requires.{field}' items must be strings",
                            file_path=skill_md,
                            line=field_line,
                        )
                    )

    def _check_install(self, openclaw, skill_md, node_line, violations):
        install = openclaw.get("install")
        if install is None:
            return

        install_line = node_line("metadata.openclaw.install")
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
            entry_path = f"metadata.openclaw.install[{i}]"
            entry_line = node_line(entry_path) or install_line

            if not isinstance(entry, dict):
                violations.append(
                    self.violation(
                        f"'metadata.openclaw.install[{i}]' must be a mapping",
                        file_path=skill_md,
                        line=entry_line,
                    )
                )
                continue

            # openclaw reads `kind`, falling back to `type` as an alias, and
            # lowercases it before matching (see parseOpenClawManifestInstallBase).
            kind_value = entry.get("kind")
            type_value = entry.get("type")
            if isinstance(kind_value, str):
                kind_field, raw_kind = "kind", kind_value
            elif isinstance(type_value, str):
                kind_field, raw_kind = "type", type_value
            elif "kind" in entry:
                kind_field, raw_kind = "kind", kind_value
            elif "type" in entry:
                kind_field, raw_kind = "type", type_value
            else:
                kind_field, raw_kind = None, None

            kind_line = None
            if kind_field is not None:
                kind_line = node_line(f"{entry_path}.{kind_field}") or entry_line

            effective_kind = None
            if kind_field is None:
                violations.append(
                    self.violation(
                        f"'metadata.openclaw.install[{i}]' must specify 'kind' or 'type'",
                        file_path=skill_md,
                        line=entry_line,
                    )
                )
            elif not isinstance(raw_kind, str):
                violations.append(
                    self.violation(
                        f"'metadata.openclaw.install[{i}].{kind_field}' must be a string",
                        file_path=skill_md,
                        line=kind_line,
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
                            line=kind_line,
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
                            line=kind_line,
                        )
                    )

            if "os" in entry:
                os_val = entry["os"]
                os_line = node_line(f"{entry_path}.os")
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
                archive_line = node_line(f"{entry_path}.archive")
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
                        line=node_line(f"{entry_path}.extract"),
                    )
                )

            if "stripComponents" in entry:
                strip_val = entry["stripComponents"]
                # bool is an int subclass in Python, but `stripComponents: true`
                # is not a strip depth — reject it explicitly.
                if isinstance(strip_val, bool) or not isinstance(strip_val, (int, float)):
                    violations.append(
                        self.violation(
                            f"'metadata.openclaw.install[{i}].stripComponents' must be a number",
                            file_path=skill_md,
                            line=node_line(f"{entry_path}.stripComponents"),
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
                            line=node_line(f"{entry_path}.{str_field}"),
                        )
                    )

            if "bins" in entry:
                bins = entry["bins"]
                bins_line = node_line(f"{entry_path}.bins")
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

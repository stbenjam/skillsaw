"""Rule: skills-lock-valid."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable, List, Mapping

from skillsaw.blocks import SkillsLockBlock
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.diagnostics import safe_display
from skillsaw.formats import skills_lock
from skillsaw.rule import Rule, RuleViolation, Severity


def _stable_key(value: object) -> str:
    """Short stable identifier for an untrusted lockfile key."""
    return hashlib.sha256(str(value).encode("utf-8", errors="replace")).hexdigest()[:16]


class SkillsLockValidRule(Rule):
    """Check that project skills lockfiles match the shape the skills CLI reads."""

    since = "0.20.0"
    repo_types = frozenset({RepositoryType.SKILLS_LOCK})

    config_schema = {
        "extra-source-types": {
            "type": "list",
            "default": [],
            "description": (
                "Additional sourceType values to accept when a newer or custom "
                "skills CLI writes sources this skillsaw release does not know"
            ),
        },
    }

    @property
    def rule_id(self) -> str:
        return "skills-lock-valid"

    @property
    def description(self) -> str:
        return "skills-lock.json files must be valid and portable project lockfiles"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        for block in context.lint_tree.find(SkillsLockBlock):
            if block.parse_error:
                violations.append(
                    self.violation(
                        f"Invalid JSON: {safe_display(block.parse_error)}",
                        file_path=block.path,
                        fingerprint_discriminator="document:json",
                    )
                )
                continue

            data = block.raw_data
            if data is None:
                violations.append(
                    self.violation(
                        "skills-lock.json must contain a JSON object",
                        file_path=block.path,
                        fingerprint_discriminator="document:not-object",
                    )
                )
                continue

            violations.extend(self._check_version(data, block.path))
            violations.extend(self._check_skills(data, block.path))
        return violations

    def _check_version(self, data: Mapping[str, Any], path: Path) -> List[RuleViolation]:
        if "version" not in data:
            return [
                self.violation(
                    f"Missing required top-level field 'version' (current version is "
                    f"{skills_lock.CURRENT_VERSION})",
                    file_path=path,
                    fingerprint_discriminator="document:version-missing",
                )
            ]

        version = data["version"]
        if isinstance(version, bool) or not isinstance(version, (int, float)):
            return [
                self.violation(
                    "Top-level 'version' must be a number",
                    file_path=path,
                    fingerprint_discriminator="document:version-type",
                )
            ]
        if version < 1:
            return [
                self.violation(
                    "Top-level 'version' must be at least 1",
                    file_path=path,
                    fingerprint_discriminator="document:version-old",
                )
            ]
        if version > skills_lock.CURRENT_VERSION:
            return [
                self.violation(
                    f"Lockfile version {safe_display(version)} is newer than the supported "
                    f"version {skills_lock.CURRENT_VERSION}; known fields were checked "
                    "permissively",
                    file_path=path,
                    severity=Severity.WARNING,
                    fingerprint_discriminator="document:version-new",
                )
            ]
        return []

    def _check_skills(self, data: Mapping[str, Any], path: Path) -> List[RuleViolation]:
        if "skills" not in data:
            return [
                self.violation(
                    "Missing required top-level field 'skills'",
                    file_path=path,
                    fingerprint_discriminator="document:skills-missing",
                )
            ]

        entries = data["skills"]
        if not isinstance(entries, dict):
            return [
                self.violation(
                    "Top-level 'skills' must be an object keyed by installed skill name",
                    file_path=path,
                    fingerprint_discriminator="document:skills-type",
                )
            ]

        violations: List[RuleViolation] = []
        for name, entry in entries.items():
            discriminator = f"skill:{_stable_key(name)}"
            shown_name = safe_display(name)
            if not name.strip():
                violations.append(
                    self.violation(
                        "Skill names in 'skills' must not be empty",
                        file_path=path,
                        fingerprint_discriminator=f"{discriminator}:name-empty",
                    )
                )
            if not isinstance(entry, dict):
                violations.append(
                    self.violation(
                        f"Skill '{shown_name}' must be an object",
                        file_path=path,
                        fingerprint_discriminator=f"{discriminator}:entry-type",
                    )
                )
                continue
            violations.extend(self._check_entry(name, entry, path, discriminator))
        return violations

    def _check_entry(
        self,
        name: str,
        entry: Mapping[str, Any],
        path: Path,
        discriminator: str,
    ) -> List[RuleViolation]:
        shown_name = safe_display(name)
        violations: List[RuleViolation] = []

        for field in ("source", "sourceType"):
            value = entry.get(field)
            if not isinstance(value, str) or not value.strip():
                violations.append(
                    self.violation(
                        f"Skill '{shown_name}' field '{field}' must be a non-empty string",
                        file_path=path,
                        fingerprint_discriminator=f"{discriminator}:{field}-required",
                    )
                )

        # The CLI reads `computedHash` only to detect drift (`skills check`
        # / `sync`); `list`, `add` and `update` process an entry without it.
        # A hand-maintained or older lockfile that omits it still works, so
        # the omission is a warning — a malformed digest stays an error below.
        computed_hash = entry.get("computedHash")
        if computed_hash is None or (isinstance(computed_hash, str) and not computed_hash.strip()):
            violations.append(
                self.violation(
                    f"Skill '{shown_name}' has no 'computedHash'; `npx skills` cannot "
                    "detect drift for it until the lockfile is regenerated",
                    file_path=path,
                    severity=Severity.WARNING,
                    fingerprint_discriminator=f"{discriminator}:computedHash-required",
                )
            )
        elif not isinstance(computed_hash, str):
            # Present but the wrong type is a malformed entry, not an absent
            # digest: the CLI never writes a number or an object here.
            violations.append(
                self.violation(
                    f"Skill '{shown_name}' field 'computedHash' must be a string",
                    file_path=path,
                    fingerprint_discriminator=f"{discriminator}:computedHash-format",
                )
            )

        source = entry.get("source")
        source_type = entry.get("sourceType")
        computed_hash = entry.get("computedHash")

        if isinstance(computed_hash, str) and computed_hash.strip():
            if not skills_lock.COMPUTED_HASH_RE.fullmatch(computed_hash):
                violations.append(
                    self.violation(
                        f"Skill '{shown_name}' field 'computedHash' must be a lowercase "
                        "64-character SHA-256 hex digest",
                        file_path=path,
                        fingerprint_discriminator=f"{discriminator}:computedHash-format",
                    )
                )

        if isinstance(source_type, str) and source_type.strip():
            accepted_types = skills_lock.SOURCE_TYPES | self._extra_source_types()
            if source_type not in accepted_types:
                violations.append(
                    self.violation(
                        f"Skill '{shown_name}' uses unrecognized sourceType "
                        f"'{safe_display(source_type)}'. If it was added after this skillsaw "
                        "release, list it under skills-lock-valid 'extra-source-types'.",
                        file_path=path,
                        severity=Severity.INFO,
                        fingerprint_discriminator=f"{discriminator}:sourceType-unknown",
                    )
                )

        for field in ("sourceUrl", "ref", "skillPath", "wellKnownDigest"):
            if field not in entry:
                continue
            value = entry[field]
            if not isinstance(value, str) or not value.strip():
                violations.append(
                    self.violation(
                        f"Skill '{shown_name}' optional field '{field}' must be a non-empty "
                        "string when present",
                        file_path=path,
                        fingerprint_discriminator=f"{discriminator}:{field}-type",
                    )
                )

        subagents = entry.get("subagents")
        if "subagents" in entry:
            if not isinstance(subagents, list):
                violations.append(
                    self.violation(
                        f"Skill '{shown_name}' optional field 'subagents' must be an array "
                        "of strings",
                        file_path=path,
                        fingerprint_discriminator=f"{discriminator}:subagents-type",
                    )
                )
            else:
                violations.extend(self._check_subagents(shown_name, subagents, path, discriminator))

        if (
            isinstance(source, str)
            and source.strip()
            and isinstance(source_type, str)
            and source_type in {"git", "gitlab"}
            and skills_lock.is_bare_git_source(source)
            and "sourceUrl" not in entry
        ):
            violations.append(
                self.violation(
                    f"Skill '{shown_name}' uses a bare {source_type} source without "
                    "'sourceUrl'; the skills CLI cannot restore or update it reliably",
                    file_path=path,
                    severity=Severity.WARNING,
                    fingerprint_discriminator=f"{discriminator}:sourceUrl-missing",
                )
            )

        if (
            source_type == "local"
            and isinstance(source, str)
            and source.strip()
            and skills_lock.is_absolute_path(source)
        ):
            violations.append(
                self.violation(
                    f"Skill '{shown_name}' uses an absolute local source path; use a "
                    "project-relative path so the lockfile is portable",
                    file_path=path,
                    severity=Severity.WARNING,
                    fingerprint_discriminator=f"{discriminator}:source-absolute",
                )
            )

        skill_path = entry.get("skillPath")
        if isinstance(skill_path, str) and skill_path.strip():
            violations.extend(self._check_skill_path(shown_name, skill_path, path, discriminator))

        digest = entry.get("wellKnownDigest")
        if isinstance(digest, str) and digest.strip():
            if not skills_lock.WELL_KNOWN_DIGEST_RE.fullmatch(digest):
                violations.append(
                    self.violation(
                        f"Skill '{shown_name}' field 'wellKnownDigest' must use "
                        "'sha256:' followed by 64 lowercase hex characters",
                        file_path=path,
                        fingerprint_discriminator=f"{discriminator}:wellKnownDigest-format",
                    )
                )

        return violations

    def _extra_source_types(self) -> frozenset[str]:
        configured = self.setting("extra-source-types")
        if not isinstance(configured, (list, tuple, set, frozenset)):
            return frozenset()
        return frozenset(value for value in configured if isinstance(value, str) and value.strip())

    def _check_subagents(
        self,
        shown_name: str,
        subagents: Iterable[Any],
        path: Path,
        discriminator: str,
    ) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        for index, value in enumerate(subagents):
            if not isinstance(value, str):
                violations.append(
                    self.violation(
                        f"Skill '{shown_name}' subagents[{index}] must be a string",
                        file_path=path,
                        fingerprint_discriminator=f"{discriminator}:subagents-{index}-type",
                    )
                )
        return violations

    def _check_skill_path(
        self,
        shown_name: str,
        skill_path: str,
        path: Path,
        discriminator: str,
    ) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        if "\x00" in skill_path:
            violations.append(
                self.violation(
                    f"Skill '{shown_name}' field 'skillPath' must not contain NUL characters",
                    file_path=path,
                    fingerprint_discriminator=f"{discriminator}:skillPath-nul",
                )
            )
        if skills_lock.is_absolute_path(skill_path) or skills_lock.has_parent_segment(skill_path):
            violations.append(
                self.violation(
                    f"Skill '{shown_name}' field 'skillPath' must stay relative to the "
                    "downloaded source",
                    file_path=path,
                    fingerprint_discriminator=f"{discriminator}:skillPath-containment",
                )
            )
        if skill_path.replace("\\", "/").split("/")[-1] != "SKILL.md":
            violations.append(
                self.violation(
                    f"Skill '{shown_name}' field 'skillPath' must end with 'SKILL.md'",
                    file_path=path,
                    fingerprint_discriminator=f"{discriminator}:skillPath-suffix",
                )
            )
        if "\\" in skill_path:
            violations.append(
                self.violation(
                    f"Skill '{shown_name}' field 'skillPath' uses backslashes; use '/' so "
                    "the lockfile is portable across operating systems",
                    file_path=path,
                    severity=Severity.WARNING,
                    fingerprint_discriminator=f"{discriminator}:skillPath-backslash",
                )
            )
        return violations

"""
Rules for validating Kiro steering files (.kiro/steering/*.md)
"""

import fnmatch
import re
from pathlib import Path
from typing import List, Optional

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext, HAS_KIRO
from skillsaw.rules.builtin.utils import read_text, parse_frontmatter, frontmatter_key_line

_VALID_INCLUSION_MODES = {"always", "fileMatch", "manual", "auto"}


def _is_valid_glob(pattern: str) -> bool:
    try:
        re.compile(fnmatch.translate(pattern))
        return True
    except re.error:
        return False


class KiroSteeringValidRule(Rule):
    """Validate .kiro/steering/*.md files: valid frontmatter, known keys, correct types"""

    repo_types = None
    formats = {HAS_KIRO}

    @property
    def rule_id(self) -> str:
        return "kiro-steering-valid"

    @property
    def description(self) -> str:
        return (
            "Kiro steering files must have valid frontmatter "
            "with known inclusion mode and correct types"
        )

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []

        steering_dir = context.root_path / ".kiro" / "steering"
        if not steering_dir.is_dir():
            return violations

        for file_path in sorted(steering_dir.rglob("*")):
            if file_path.is_dir():
                continue

            if file_path.suffix.lower() != ".md":
                violations.append(
                    self.violation(
                        f"Non-.md file in .kiro/steering/: '{file_path.name}' "
                        f"(only .md files are loaded by Kiro)",
                        file_path=file_path,
                        severity=Severity.WARNING,
                    )
                )
                continue

            content = read_text(file_path)
            if content is None:
                violations.append(
                    self.violation(
                        f"Failed to read file: {file_path}",
                        file_path=file_path,
                    )
                )
                continue

            if not content.strip():
                violations.append(
                    self.violation(
                        "Empty steering file",
                        file_path=file_path,
                        severity=Severity.WARNING,
                    )
                )
                continue

            frontmatter, body = parse_frontmatter(content)
            if frontmatter is not None:
                self._check_frontmatter(file_path, frontmatter, violations)

            if not body.strip():
                violations.append(
                    self.violation(
                        "Steering file has frontmatter but no content body",
                        file_path=file_path,
                        severity=Severity.WARNING,
                    )
                )

        return violations

    def _check_frontmatter(
        self,
        file_path: Path,
        frontmatter: dict,
        violations: List[RuleViolation],
    ) -> None:
        inclusion = frontmatter.get("inclusion")
        if inclusion is not None:
            self._check_inclusion(file_path, frontmatter, violations)

        if "fileMatchPattern" in frontmatter:
            self._check_file_match_pattern(file_path, frontmatter, violations)

        if "name" in frontmatter:
            name = frontmatter["name"]
            line = frontmatter_key_line(file_path, "name")
            if not isinstance(name, str):
                violations.append(
                    self.violation(
                        f"'name' must be a string, got {type(name).__name__}",
                        file_path=file_path,
                        line=line,
                    )
                )
            elif not name.strip():
                violations.append(
                    self.violation(
                        "'name' is empty",
                        file_path=file_path,
                        line=line,
                        severity=Severity.WARNING,
                    )
                )

        if "description" in frontmatter:
            desc = frontmatter["description"]
            line = frontmatter_key_line(file_path, "description")
            if not isinstance(desc, str):
                violations.append(
                    self.violation(
                        f"'description' must be a string, got {type(desc).__name__}",
                        file_path=file_path,
                        line=line,
                    )
                )
            elif not desc.strip():
                violations.append(
                    self.violation(
                        "'description' is empty",
                        file_path=file_path,
                        line=line,
                        severity=Severity.WARNING,
                    )
                )

    def _check_inclusion(
        self,
        file_path: Path,
        frontmatter: dict,
        violations: List[RuleViolation],
    ) -> None:
        inclusion = frontmatter["inclusion"]
        line = frontmatter_key_line(file_path, "inclusion")

        if not isinstance(inclusion, str):
            violations.append(
                self.violation(
                    f"'inclusion' must be a string, got {type(inclusion).__name__}",
                    file_path=file_path,
                    line=line,
                )
            )
            return

        if inclusion not in _VALID_INCLUSION_MODES:
            violations.append(
                self.violation(
                    f"Unknown inclusion mode '{inclusion}'. "
                    f"Valid modes: always, fileMatch, manual, auto",
                    file_path=file_path,
                    line=line,
                )
            )
            return

        if inclusion == "fileMatch" and "fileMatchPattern" not in frontmatter:
            violations.append(
                self.violation(
                    "inclusion is 'fileMatch' but 'fileMatchPattern' is missing",
                    file_path=file_path,
                    line=line,
                )
            )

        if inclusion == "auto":
            if "name" not in frontmatter:
                violations.append(
                    self.violation(
                        "inclusion is 'auto' but required 'name' field is missing",
                        file_path=file_path,
                        line=line,
                    )
                )
            if "description" not in frontmatter:
                violations.append(
                    self.violation(
                        "inclusion is 'auto' but required 'description' field is missing",
                        file_path=file_path,
                        line=line,
                    )
                )

    def _check_file_match_pattern(
        self,
        file_path: Path,
        frontmatter: dict,
        violations: List[RuleViolation],
    ) -> None:
        value = frontmatter["fileMatchPattern"]
        line = frontmatter_key_line(file_path, "fileMatchPattern")

        if isinstance(value, str):
            patterns = [value]
        elif isinstance(value, list):
            patterns = value
        else:
            violations.append(
                self.violation(
                    f"'fileMatchPattern' must be a string or list of strings, "
                    f"got {type(value).__name__}",
                    file_path=file_path,
                    line=line,
                )
            )
            return

        for pattern in patterns:
            if not isinstance(pattern, str):
                violations.append(
                    self.violation(
                        f"'fileMatchPattern' contains non-string value: {pattern!r}",
                        file_path=file_path,
                        line=line,
                    )
                )
            elif not pattern.strip():
                violations.append(
                    self.violation(
                        "'fileMatchPattern' contains empty pattern",
                        file_path=file_path,
                        line=line,
                        severity=Severity.WARNING,
                    )
                )
            elif not _is_valid_glob(pattern):
                violations.append(
                    self.violation(
                        f"'fileMatchPattern' contains invalid glob pattern: {pattern!r}",
                        file_path=file_path,
                        line=line,
                    )
                )

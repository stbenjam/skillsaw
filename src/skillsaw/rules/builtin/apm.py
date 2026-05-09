"""
Rules for validating APM (Agent Package Manager) format repositories
"""

import re
from typing import List, Optional

import yaml

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.utils import read_text


def _yaml_key_line(file_path, key: str) -> Optional[int]:
    """Find the line number of a top-level key in a YAML file."""
    content = read_text(file_path)
    if content is None:
        return None
    pattern = re.compile(rf"^{re.escape(key)}\s*:")
    for i, line in enumerate(content.splitlines(), 1):
        if pattern.match(line):
            return i
    return None


class ApmYamlValidRule(Rule):
    """Validate that apm.yml exists and has required fields"""

    repo_types = None  # runs when enabled; auto-enable via config + has_apm check

    since = "0.7.0"

    @property
    def rule_id(self) -> str:
        return "apm-yaml-valid"

    @property
    def description(self) -> str:
        return "apm.yml must exist with valid YAML and required fields (name, version, description)"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        if not context.has_apm:
            return []

        violations = []
        apm_yml = context.root_path / "apm.yml"

        if not apm_yml.exists():
            violations.append(
                self.violation(
                    "Missing apm.yml at repository root (required for APM repos)",
                )
            )
            return violations

        content = read_text(apm_yml)
        if content is None:
            violations.append(
                self.violation(
                    "Failed to read apm.yml (invalid encoding or I/O error)",
                    file_path=apm_yml,
                )
            )
            return violations

        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError as e:
            violations.append(
                self.violation(
                    f"Invalid YAML in apm.yml: {e}",
                    file_path=apm_yml,
                )
            )
            return violations

        if not isinstance(data, dict):
            violations.append(
                self.violation(
                    "apm.yml must be a YAML mapping",
                    file_path=apm_yml,
                )
            )
            return violations

        # Required fields
        for field in ("name", "version", "description"):
            value = data.get(field)
            if not value:
                violations.append(
                    self.violation(
                        f"Missing required field '{field}' in apm.yml",
                        file_path=apm_yml,
                    )
                )
            elif not isinstance(value, str):
                violations.append(
                    self.violation(
                        f"Field '{field}' must be a string in apm.yml",
                        file_path=apm_yml,
                        line=_yaml_key_line(apm_yml, field),
                    )
                )

        return violations


class ApmStructureValidRule(Rule):
    """Validate .apm/ directory structure"""

    repo_types = None  # runs when enabled; auto-enable via config + has_apm check

    since = "0.7.0"

    @property
    def rule_id(self) -> str:
        return "apm-structure-valid"

    @property
    def description(self) -> str:
        return ".apm/ directory must contain skills/ or instructions/ with valid structure"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        if not context.has_apm:
            return []

        violations = []
        apm_dir = context.root_path / ".apm"

        # Check that .apm/ has at least one of the expected subdirectories
        has_skills = (apm_dir / "skills").is_dir()
        has_instructions = (apm_dir / "instructions").is_dir()

        if not has_skills and not has_instructions:
            violations.append(
                self.violation(
                    ".apm/ directory should contain a 'skills/' or 'instructions/' subdirectory",
                    file_path=apm_dir,
                )
            )

        # Validate that each skill subdirectory has SKILL.md
        if has_skills:
            skills_dir = apm_dir / "skills"
            try:
                for item in skills_dir.iterdir():
                    if not item.is_dir() or item.name.startswith("."):
                        continue
                    if not (item / "SKILL.md").exists():
                        violations.append(
                            self.violation(
                                f"Skill directory '{item.name}' is missing SKILL.md",
                                file_path=item,
                            )
                        )
            except OSError:
                pass

        return violations

"""
Rules for validating .claude/rules/ directory structure and content
"""

import re
from pathlib import Path
from typing import List

import yaml

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.rules.builtin.utils import read_text, frontmatter_key_line, validate_glob_patterns


def _parse_frontmatter(content: str):
    """Parse YAML frontmatter from markdown content.

    Returns (frontmatter_dict, error_message). If no frontmatter is present,
    returns (None, None). If parsing fails, returns (None, error_string).
    """
    if not content.startswith("---"):
        return None, None

    match = re.match(r"^---[ \t]*\n(.*?\n)?---[ \t]*(?:\n|$)", content, re.DOTALL)
    if not match:
        return None, "Unterminated frontmatter (missing closing '---')"

    raw = (match.group(1) or "").rstrip("\n")
    try:
        data = yaml.safe_load(raw) if raw else None
    except yaml.YAMLError as e:
        return None, f"Invalid YAML in frontmatter: {e}"

    if data is None:
        return {}, None
    if not isinstance(data, dict):
        return None, "Frontmatter must be a YAML mapping"
    return data, None


_DEFAULT_VALID_KEYS = ["paths"]


class RulesValidRule(Rule):
    """Validate .claude/rules/ files: markdown extension, valid frontmatter, valid path globs"""

    repo_types = {RepositoryType.DOT_CLAUDE}

    config_schema = {
        "valid-keys": {
            "type": "list",
            "default": _DEFAULT_VALID_KEYS,
            "description": "Recognized frontmatter keys (unknown keys trigger a warning)",
        },
    }

    @property
    def rule_id(self) -> str:
        return "rules-valid"

    @property
    def description(self) -> str:
        return ".claude/rules/ files must be markdown with valid optional paths frontmatter"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def _find_rules_dir(self, context: RepositoryContext) -> Path:
        claude_dir = context.root_path
        if context.root_path.name != ".claude":
            claude_dir = context.root_path / ".claude"
        return claude_dir / "rules"

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []

        rules_dir = self._find_rules_dir(context)
        if not rules_dir.is_dir():
            return violations

        for file_path in sorted(rules_dir.rglob("*")):
            if file_path.is_dir():
                continue

            if file_path.suffix.lower() != ".md":
                violations.append(
                    self.violation(
                        f"Non-markdown file in rules/ directory: '{file_path.name}' "
                        f"(only .md files are loaded)",
                        file_path=file_path,
                        severity=Severity.WARNING,
                    )
                )
                continue

            content = read_text(file_path)
            if content is None:
                violations.append(
                    self.violation(f"Failed to read file: {file_path}", file_path=file_path)
                )
                continue

            frontmatter, error = _parse_frontmatter(content)
            if error:
                violations.append(self.violation(error, file_path=file_path))
                continue

            if frontmatter is None:
                continue

            valid_keys = set(self.config.get("valid-keys", _DEFAULT_VALID_KEYS))
            unknown_keys = set(frontmatter.keys()) - valid_keys
            if unknown_keys:
                for key in sorted(unknown_keys):
                    violations.append(
                        self.violation(
                            f"Unknown frontmatter key '{key}'",
                            file_path=file_path,
                            line=frontmatter_key_line(file_path, key),
                            severity=Severity.WARNING,
                        )
                    )

            if "paths" not in frontmatter:
                continue

            paths_line = frontmatter_key_line(file_path, "paths")
            paths = frontmatter["paths"]
            if not isinstance(paths, list):
                violations.append(
                    self.violation(
                        "'paths' must be a list of glob patterns",
                        file_path=file_path,
                        line=paths_line,
                    )
                )
                continue

            for error in validate_glob_patterns(paths, field_name="paths"):
                violations.append(self.violation(error, file_path=file_path, line=paths_line))

        return violations

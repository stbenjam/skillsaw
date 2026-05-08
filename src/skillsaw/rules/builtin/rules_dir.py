"""
Rules for validating .claude/rules/ directory structure and content
"""

import re
from pathlib import Path
from typing import List

import yaml

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.rules.builtin.utils import read_text, frontmatter_key_line


def _parse_frontmatter(content: str):
    """Parse YAML frontmatter from markdown content.

    Returns (frontmatter_dict, error_message). If no frontmatter is present,
    returns (None, None). If parsing fails, returns (None, error_string).
    """
    if not content.startswith("---"):
        return None, None

    match = re.match(r"^---\n(.*?)---", content, re.DOTALL)
    if not match:
        return None, "Unterminated frontmatter (missing closing '---')"

    raw = match.group(1).rstrip("\n")
    try:
        data = yaml.safe_load(raw) if raw else None
    except yaml.YAMLError as e:
        return None, f"Invalid YAML in frontmatter: {e}"

    if data is None:
        return {}, None
    if not isinstance(data, dict):
        return None, "Frontmatter must be a YAML mapping"
    return data, None


_VALID_FRONTMATTER_KEYS = {"paths"}


class RulesValidRule(Rule):
    """Validate .claude/rules/ files: markdown extension, valid frontmatter, valid path globs"""

    repo_types = {RepositoryType.DOT_CLAUDE}

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

            unknown_keys = set(frontmatter.keys()) - _VALID_FRONTMATTER_KEYS
            if unknown_keys:
                for key in sorted(unknown_keys):
                    violations.append(
                        self.violation(
                            f"Unknown frontmatter key '{key}'. "
                            f"Only 'paths' is supported",
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

            for i, pattern in enumerate(paths):
                if not isinstance(pattern, str):
                    violations.append(
                        self.violation(
                            f"paths[{i}]: must be a string, got {type(pattern).__name__}",
                            file_path=file_path,
                            line=paths_line,
                        )
                    )
                    continue

                if not pattern.strip():
                    violations.append(
                        self.violation(
                            f"paths[{i}]: empty glob pattern",
                            file_path=file_path,
                            line=paths_line,
                        )
                    )
                    continue

                if pattern.startswith("/") or pattern.startswith("\\"):
                    violations.append(
                        self.violation(
                            f"paths[{i}]: '{pattern}' must be a relative path, not absolute",
                            file_path=file_path,
                            line=paths_line,
                        )
                    )

                normalized = pattern.replace("\\", "/")
                segments = normalized.split("/")
                if ".." in segments:
                    violations.append(
                        self.violation(
                            f"paths[{i}]: '{pattern}' must not contain '..' segments",
                            file_path=file_path,
                            line=paths_line,
                        )
                    )

        return violations

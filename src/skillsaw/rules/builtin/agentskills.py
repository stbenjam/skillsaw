"""
Rules for validating agentskills.io skill format
"""

import json
import re
from functools import lru_cache
from typing import List, Optional, Tuple, Dict

import yaml

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext, RepositoryType

# agentskills.io spec constraints
NAME_MAX_LENGTH = 64
DESCRIPTION_MAX_LENGTH = 1024
COMPATIBILITY_MAX_LENGTH = 500
NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
CONSECUTIVE_HYPHENS = re.compile(r"--")


@lru_cache(maxsize=None)
def _parse_skill_md(skill_path) -> Tuple[Optional[Dict], Optional[str]]:
    """
    Parse SKILL.md frontmatter from a skill directory.

    Returns (frontmatter_dict, error_string). If error_string is set,
    frontmatter_dict is None. Results are cached per path.
    """
    skill_md = skill_path / "SKILL.md"
    if not skill_md.exists():
        return None, "SKILL.md not found"

    try:
        content = skill_md.read_text()
    except IOError as e:
        return None, f"Failed to read SKILL.md: {e}"

    if not content.startswith("---"):
        return None, "Missing YAML frontmatter (must start with ---)"

    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?", content, re.DOTALL)
    if not match:
        return None, "Invalid frontmatter (missing closing ---)"

    try:
        frontmatter = yaml.safe_load(match.group(1))
    except yaml.YAMLError as e:
        return None, f"Invalid YAML in frontmatter: {e}"

    if not isinstance(frontmatter, dict):
        return None, "Frontmatter must be a YAML mapping"

    return frontmatter, None


class AgentSkillValidRule(Rule):
    """Validate SKILL.md exists with required frontmatter fields"""

    repo_types = {
        RepositoryType.AGENTSKILLS,
        RepositoryType.SINGLE_PLUGIN,
        RepositoryType.MARKETPLACE,
        RepositoryType.DOT_CLAUDE,
    }

    @property
    def rule_id(self) -> str:
        return "agentskill-valid"

    @property
    def description(self) -> str:
        return "SKILL.md must have valid frontmatter with name and description"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        for skill_path in context.skills:
            skill_md = skill_path / "SKILL.md"
            frontmatter, error = _parse_skill_md(skill_path)

            if error:
                violations.append(self.violation(error, file_path=skill_md))
                continue

            name = frontmatter.get("name")
            if not name:
                violations.append(
                    self.violation("Missing required 'name' field", file_path=skill_md)
                )
            elif not isinstance(name, str):
                violations.append(self.violation("'name' must be a string", file_path=skill_md))
            elif len(name) > NAME_MAX_LENGTH:
                violations.append(
                    self.violation(
                        f"'name' exceeds {NAME_MAX_LENGTH} characters ({len(name)})",
                        file_path=skill_md,
                    )
                )

            desc = frontmatter.get("description")
            if not desc:
                violations.append(
                    self.violation("Missing required 'description' field", file_path=skill_md)
                )
            elif not isinstance(desc, str):
                violations.append(
                    self.violation("'description' must be a string", file_path=skill_md)
                )

            if "license" in frontmatter and not isinstance(frontmatter["license"], str):
                violations.append(self.violation("'license' must be a string", file_path=skill_md))

            if "compatibility" in frontmatter:
                compat = frontmatter["compatibility"]
                if not isinstance(compat, str):
                    violations.append(
                        self.violation("'compatibility' must be a string", file_path=skill_md)
                    )
                elif not compat.strip():
                    violations.append(
                        self.violation(
                            "'compatibility' must not be empty if provided",
                            file_path=skill_md,
                        )
                    )
                elif len(compat) > COMPATIBILITY_MAX_LENGTH:
                    violations.append(
                        self.violation(
                            f"'compatibility' exceeds {COMPATIBILITY_MAX_LENGTH} characters ({len(compat)})",
                            file_path=skill_md,
                        )
                    )

            if "metadata" in frontmatter:
                meta = frontmatter["metadata"]
                if not isinstance(meta, dict):
                    violations.append(
                        self.violation("'metadata' must be a mapping", file_path=skill_md)
                    )
                else:
                    for k, v in meta.items():
                        if not isinstance(k, str):
                            violations.append(
                                self.violation(
                                    f"'metadata' key {k!r} must be a string",
                                    file_path=skill_md,
                                )
                            )

            if "allowed-tools" in frontmatter and not isinstance(frontmatter["allowed-tools"], str):
                violations.append(
                    self.violation("'allowed-tools' must be a string", file_path=skill_md)
                )

        return violations


class AgentSkillNameRule(Rule):
    """Validate skill name format per agentskills.io spec"""

    repo_types = {
        RepositoryType.AGENTSKILLS,
        RepositoryType.SINGLE_PLUGIN,
        RepositoryType.MARKETPLACE,
        RepositoryType.DOT_CLAUDE,
    }

    @property
    def rule_id(self) -> str:
        return "agentskill-name"

    @property
    def description(self) -> str:
        return "Skill name must be lowercase with hyphens and match directory name"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        for skill_path in context.skills:
            skill_md = skill_path / "SKILL.md"
            frontmatter, error = _parse_skill_md(skill_path)

            if error or not frontmatter:
                continue

            name = frontmatter.get("name")
            if not name or not isinstance(name, str):
                continue

            if not NAME_PATTERN.match(name):
                violations.append(
                    self.violation(
                        f"Name '{name}' must contain only lowercase letters, numbers, and hyphens",
                        file_path=skill_md,
                    )
                )
                continue

            if name.endswith("-"):
                violations.append(
                    self.violation(
                        f"Name '{name}' must not end with a hyphen",
                        file_path=skill_md,
                    )
                )

            if CONSECUTIVE_HYPHENS.search(name):
                violations.append(
                    self.violation(
                        f"Name '{name}' must not contain consecutive hyphens",
                        file_path=skill_md,
                    )
                )

            # Name must match parent directory (skip if skill is at repo root)
            if skill_path != context.root_path and name != skill_path.name:
                violations.append(
                    self.violation(
                        f"Name '{name}' does not match directory name '{skill_path.name}'",
                        file_path=skill_md,
                    )
                )

        return violations


class AgentSkillDescriptionRule(Rule):
    """Validate skill description quality"""

    repo_types = {
        RepositoryType.AGENTSKILLS,
        RepositoryType.SINGLE_PLUGIN,
        RepositoryType.MARKETPLACE,
        RepositoryType.DOT_CLAUDE,
    }

    @property
    def rule_id(self) -> str:
        return "agentskill-description"

    @property
    def description(self) -> str:
        return "Skill description should be meaningful and within length limits"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        for skill_path in context.skills:
            skill_md = skill_path / "SKILL.md"
            frontmatter, error = _parse_skill_md(skill_path)

            if error or not frontmatter:
                continue

            desc = frontmatter.get("description")
            if not desc or not isinstance(desc, str):
                continue

            stripped = desc.strip()
            if not stripped:
                violations.append(
                    self.violation("Description is empty or whitespace-only", file_path=skill_md)
                )
                continue

            if len(stripped) > DESCRIPTION_MAX_LENGTH:
                violations.append(
                    self.violation(
                        f"Description exceeds {DESCRIPTION_MAX_LENGTH} characters ({len(stripped)})",
                        file_path=skill_md,
                    )
                )

        return violations


class AgentSkillStructureRule(Rule):
    """Validate skill directory structure"""

    repo_types = {
        RepositoryType.AGENTSKILLS,
        RepositoryType.SINGLE_PLUGIN,
        RepositoryType.MARKETPLACE,
        RepositoryType.DOT_CLAUDE,
    }

    @property
    def rule_id(self) -> str:
        return "agentskill-structure"

    @property
    def description(self) -> str:
        return "Skill directories should only contain recognized subdirectories"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        # The agentskills.io spec allows arbitrary directories inside a skill,
        # so this rule no longer flags unrecognized directory names.
        return []


class AgentSkillEvalsRequiredRule(Rule):
    """Require evals/evals.json in each skill"""

    repo_types = {
        RepositoryType.AGENTSKILLS,
        RepositoryType.SINGLE_PLUGIN,
        RepositoryType.MARKETPLACE,
        RepositoryType.DOT_CLAUDE,
    }

    @property
    def rule_id(self) -> str:
        return "agentskill-evals-required"

    @property
    def description(self) -> str:
        return "Require evals/evals.json for each skill (opt-in)"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        for skill_path in context.skills:
            evals_json = skill_path / "evals" / "evals.json"
            if not evals_json.exists():
                violations.append(
                    self.violation(
                        "Missing evals/evals.json",
                        file_path=skill_path,
                    )
                )

        return violations


class AgentSkillEvalsRule(Rule):
    """Validate evals/evals.json structure"""

    repo_types = {
        RepositoryType.AGENTSKILLS,
        RepositoryType.SINGLE_PLUGIN,
        RepositoryType.MARKETPLACE,
        RepositoryType.DOT_CLAUDE,
    }

    @property
    def rule_id(self) -> str:
        return "agentskill-evals"

    @property
    def description(self) -> str:
        return "Validate evals/evals.json format when present"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        for skill_path in context.skills:
            evals_dir = skill_path / "evals"
            evals_json = evals_dir / "evals.json"

            if not evals_dir.is_dir():
                continue

            if not evals_json.exists():
                violations.append(
                    self.violation(
                        "evals/ directory exists but evals.json is missing",
                        file_path=evals_dir,
                    )
                )
                continue

            try:
                data = json.loads(evals_json.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                violations.append(
                    self.violation(f"Invalid JSON in evals.json: {e}", file_path=evals_json)
                )
                continue
            except IOError as e:
                violations.append(
                    self.violation(f"Failed to read evals.json: {e}", file_path=evals_json)
                )
                continue

            if not isinstance(data, dict):
                violations.append(
                    self.violation("evals.json must be a JSON object", file_path=evals_json)
                )
                continue

            skill_name = data.get("skill_name")
            if skill_name is not None and not isinstance(skill_name, str):
                violations.append(
                    self.violation("'skill_name' must be a string", file_path=evals_json)
                )
            elif isinstance(skill_name, str):
                frontmatter, _ = _parse_skill_md(skill_path)
                if frontmatter and frontmatter.get("name") != skill_name:
                    violations.append(
                        self.violation(
                            f"'skill_name' ({skill_name!r}) does not match "
                            f"SKILL.md name ({frontmatter.get('name')!r})",
                            file_path=evals_json,
                        )
                    )

            evals = data.get("evals")
            if evals is None:
                violations.append(
                    self.violation("Missing required 'evals' array", file_path=evals_json)
                )
                continue

            if not isinstance(evals, list):
                violations.append(self.violation("'evals' must be an array", file_path=evals_json))
                continue

            seen_ids = set()
            for i, entry in enumerate(evals):
                if not isinstance(entry, dict):
                    violations.append(
                        self.violation(f"evals[{i}] must be an object", file_path=evals_json)
                    )
                    continue

                if "id" not in entry:
                    violations.append(
                        self.violation(f"evals[{i}] missing required 'id'", file_path=evals_json)
                    )
                elif not isinstance(entry["id"], (int, float)):
                    violations.append(
                        self.violation(f"evals[{i}] 'id' must be a number", file_path=evals_json)
                    )
                else:
                    eval_id = entry["id"]
                    if eval_id in seen_ids:
                        violations.append(
                            self.violation(
                                f"evals[{i}] duplicate id {eval_id}", file_path=evals_json
                            )
                        )
                    seen_ids.add(eval_id)

                if "prompt" not in entry:
                    violations.append(
                        self.violation(
                            f"evals[{i}] missing required 'prompt'", file_path=evals_json
                        )
                    )
                elif not isinstance(entry["prompt"], str):
                    violations.append(
                        self.violation(
                            f"evals[{i}] 'prompt' must be a string", file_path=evals_json
                        )
                    )

                if "expected_output" in entry and not isinstance(entry["expected_output"], str):
                    violations.append(
                        self.violation(
                            f"evals[{i}] 'expected_output' must be a string",
                            file_path=evals_json,
                        )
                    )

                if "assertions" in entry:
                    assertions = entry["assertions"]
                    if not isinstance(assertions, list):
                        violations.append(
                            self.violation(
                                f"evals[{i}] 'assertions' must be an array",
                                file_path=evals_json,
                            )
                        )
                    elif not all(isinstance(a, str) for a in assertions):
                        violations.append(
                            self.violation(
                                f"evals[{i}] all assertions must be strings",
                                file_path=evals_json,
                            )
                        )

                if "files" in entry:
                    files = entry["files"]
                    if not isinstance(files, list):
                        violations.append(
                            self.violation(
                                f"evals[{i}] 'files' must be an array", file_path=evals_json
                            )
                        )
                    elif not all(isinstance(f, str) for f in files):
                        violations.append(
                            self.violation(
                                f"evals[{i}] all file paths must be strings",
                                file_path=evals_json,
                            )
                        )

        return violations

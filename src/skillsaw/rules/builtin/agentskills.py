"""
Rules for validating agentskills.io skill format
"""

import json
import re
from functools import lru_cache
from typing import List, Optional, Tuple, Dict

import yaml

from skillsaw.rule import Rule, RuleViolation, AutofixResult, AutofixConfidence, Severity
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.rules.builtin.utils import read_text, read_json, frontmatter_key_line, register_cache

# agentskills.io spec constraints
NAME_MAX_LENGTH = 64
DESCRIPTION_MAX_LENGTH = 1024
COMPATIBILITY_MAX_LENGTH = 500
NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
CONSECUTIVE_HYPHENS = re.compile(r"--")
DEFAULT_ALLOWED_DIRS = {"scripts", "references", "assets", "evals"}


def _to_kebab(name: str) -> str:
    s = re.sub(r"([a-z])([A-Z])", r"\1-\2", name)
    s = re.sub(r"[^a-z0-9]+", "-", s.lower())
    s = re.sub(r"-+", "-", s).strip("-")
    return s


@register_cache
@lru_cache(maxsize=512)
def _parse_skill_md(skill_path) -> Tuple[Optional[Dict], Optional[str]]:
    """
    Parse SKILL.md frontmatter from a skill directory.

    Returns (frontmatter_dict, error_string). If error_string is set,
    frontmatter_dict is None. Results are cached per path.
    """
    skill_md = skill_path / "SKILL.md"
    if not skill_md.exists():
        return None, "SKILL.md not found"

    content = read_text(skill_md)
    if content is None:
        return None, f"Failed to read SKILL.md: {skill_md}"

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


def _frontmatter_key_line(skill_path, key: str) -> Optional[int]:
    """Find the line number of a top-level key in SKILL.md frontmatter."""
    return frontmatter_key_line(skill_path / "SKILL.md", key)


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

    @property
    def llm_fix_prompt(self):
        return (
            "You are fixing SKILL.md files for agentskills.io skills.\n\n"
            "Rules:\n"
            "- The frontmatter must have 'name' and 'description' fields\n"
            "- 'name' should be the directory name in lowercase kebab-case\n"
            "- 'description' should be a concise one-line summary of what the skill does, "
            "derived from reading the SKILL.md body content\n"
            "- Preserve existing frontmatter fields\n"
            "- Preserve the SKILL.md body content"
        )

    def fix(
        self, context: RepositoryContext, violations: List[RuleViolation]
    ) -> List[AutofixResult]:
        results: List[AutofixResult] = []
        for v in violations:
            if not v.file_path or not v.file_path.exists():
                continue
            if "Missing required 'name'" not in v.message:
                continue
            original = v.file_path.read_text(encoding="utf-8")
            dir_name = v.file_path.parent.name
            kebab_name = _to_kebab(dir_name)
            match = re.match(r"^---\s*\n(.*?)\n---", original, re.DOTALL)
            if match:
                fm_text = match.group(1)
                new_fm = f"name: {kebab_name}\n{fm_text}"
                fixed = original.replace(match.group(0), f"---\n{new_fm}\n---", 1)
                results.append(
                    AutofixResult(
                        rule_id=self.rule_id,
                        file_path=v.file_path,
                        confidence=AutofixConfidence.SAFE,
                        original_content=original,
                        fixed_content=fixed,
                        description=f"Added name '{kebab_name}' from directory name",
                        violations_fixed=[v],
                    )
                )
        return results

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
                violations.append(
                    self.violation(
                        "'name' must be a string",
                        file_path=skill_md,
                        line=_frontmatter_key_line(skill_path, "name"),
                    )
                )
            elif len(name) > NAME_MAX_LENGTH:
                violations.append(
                    self.violation(
                        f"'name' exceeds {NAME_MAX_LENGTH} characters ({len(name)})",
                        file_path=skill_md,
                        line=_frontmatter_key_line(skill_path, "name"),
                    )
                )

            desc = frontmatter.get("description")
            if not desc:
                violations.append(
                    self.violation("Missing required 'description' field", file_path=skill_md)
                )
            elif not isinstance(desc, str):
                violations.append(
                    self.violation(
                        "'description' must be a string",
                        file_path=skill_md,
                        line=_frontmatter_key_line(skill_path, "description"),
                    )
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

            if "allowed-tools" in frontmatter:
                at = frontmatter["allowed-tools"]
                if isinstance(at, list):
                    if not all(isinstance(item, str) for item in at):
                        violations.append(
                            self.violation(
                                "'allowed-tools' list items must all be strings",
                                file_path=skill_md,
                            )
                        )
                elif not isinstance(at, str):
                    violations.append(
                        self.violation(
                            "'allowed-tools' must be a string or list of strings",
                            file_path=skill_md,
                        )
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

            name_line = _frontmatter_key_line(skill_path, "name")

            if not NAME_PATTERN.match(name):
                violations.append(
                    self.violation(
                        f"Name '{name}' must contain only lowercase letters, numbers, and hyphens",
                        file_path=skill_md,
                        line=name_line,
                    )
                )
                continue

            if name.endswith("-"):
                violations.append(
                    self.violation(
                        f"Name '{name}' must not end with a hyphen",
                        file_path=skill_md,
                        line=name_line,
                    )
                )

            if CONSECUTIVE_HYPHENS.search(name):
                violations.append(
                    self.violation(
                        f"Name '{name}' must not contain consecutive hyphens",
                        file_path=skill_md,
                        line=name_line,
                    )
                )

            if skill_path != context.root_path and name != skill_path.name:
                violations.append(
                    self.violation(
                        f"Name '{name}' does not match directory name '{skill_path.name}'",
                        file_path=skill_md,
                        line=name_line,
                    )
                )

        return violations

    def fix(
        self, context: RepositoryContext, violations: List[RuleViolation]
    ) -> List[AutofixResult]:
        results: List[AutofixResult] = []
        for v in violations:
            if not v.file_path or not v.file_path.exists():
                continue
            original = v.file_path.read_text(encoding="utf-8")
            match = re.search(r"^name:\s*(.+)$", original, re.MULTILINE)
            if not match:
                continue
            old_name = match.group(1).strip()
            if "does not match directory" in v.message:
                new_name = v.file_path.parent.name
            else:
                new_name = _to_kebab(old_name)
            if new_name == old_name or not NAME_PATTERN.match(new_name):
                continue
            fixed = original[: match.start()] + f"name: {new_name}" + original[match.end() :]
            results.append(
                AutofixResult(
                    rule_id=self.rule_id,
                    file_path=v.file_path,
                    confidence=AutofixConfidence.SAFE,
                    original_content=original,
                    fixed_content=fixed,
                    description=f"Renamed '{old_name}' to '{new_name}'",
                    violations_fixed=[v],
                )
            )
        return results


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

            desc_line = _frontmatter_key_line(skill_path, "description")
            stripped = desc.strip()
            if not stripped:
                violations.append(
                    self.violation(
                        "Description is empty or whitespace-only",
                        file_path=skill_md,
                        line=desc_line,
                    )
                )
                continue

            if len(stripped) > DESCRIPTION_MAX_LENGTH:
                violations.append(
                    self.violation(
                        f"Description exceeds {DESCRIPTION_MAX_LENGTH} characters ({len(stripped)})",
                        file_path=skill_md,
                        line=desc_line,
                    )
                )

        return violations


class AgentSkillStructureRule(Rule):
    """Validate skill directory structure (stricter than spec)"""

    repo_types = {
        RepositoryType.AGENTSKILLS,
        RepositoryType.SINGLE_PLUGIN,
        RepositoryType.MARKETPLACE,
        RepositoryType.DOT_CLAUDE,
    }
    config_schema = {
        "allowed_dirs": {
            "type": "list",
            "default": sorted(DEFAULT_ALLOWED_DIRS),
            "description": "Directory names allowed in the skill root",
        },
    }

    @property
    def rule_id(self) -> str:
        return "agentskill-structure"

    @property
    def description(self) -> str:
        return (
            "Skill directories should only contain recognized subdirectories (stricter than spec)"
        )

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        allowed = set(self.config.get("allowed_dirs", DEFAULT_ALLOWED_DIRS))

        for skill_path in context.skills:
            try:
                for item in skill_path.iterdir():
                    if not item.is_dir() or item.name.startswith("."):
                        continue
                    if item.name not in allowed:
                        violations.append(
                            self.violation(
                                f"Unrecognized directory '{item.name}' "
                                f"(expected: {', '.join(sorted(allowed))})",
                                file_path=item,
                            )
                        )
            except OSError:
                pass

        return violations


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
        return Severity.ERROR

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
        return Severity.ERROR

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

            data, error = read_json(evals_json)
            if error:
                violations.append(
                    self.violation(f"Invalid JSON in evals.json: {error}", file_path=evals_json)
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

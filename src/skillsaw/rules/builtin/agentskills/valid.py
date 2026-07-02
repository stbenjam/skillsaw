"""AgentSkill SKILL.md validation rule"""

from typing import List

from skillsaw.rule import Rule, RuleViolation, AutofixResult, AutofixConfidence, Severity
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.lint_target import SkillNode
from skillsaw.rules.builtin.content_analysis import SkillBlock
from skillsaw.rules.builtin.utils import (
    prepend_frontmatter_fields,
    read_text,
    replace_frontmatter_field,
)

from ._helpers import NAME_MAX_LENGTH, DESCRIPTION_MAX_LENGTH, COMPATIBILITY_MAX_LENGTH, _to_kebab


class AgentSkillValidRule(Rule):
    """Validate SKILL.md exists with required frontmatter fields"""

    autofix_confidence = AutofixConfidence.SAFE

    repo_types = {
        RepositoryType.AGENTSKILLS,
        RepositoryType.SINGLE_PLUGIN,
        RepositoryType.MARKETPLACE,
        RepositoryType.DOT_CLAUDE,
    }

    BUILTIN_REQUIRED = {"name", "description"}

    config_schema = {
        "required-fields": {
            "type": "list",
            "default": [],
            "description": "Additional frontmatter fields to require (name and description are always required)",
        },
        "required-metadata": {
            "type": "list",
            "default": [],
            "description": "Keys that must be present inside the metadata mapping",
        },
    }

    @property
    def rule_id(self) -> str:
        return "agentskill-valid"

    @property
    def description(self) -> str:
        return "SKILL.md must have valid frontmatter with name and description"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def fix(
        self, context: RepositoryContext, violations: List[RuleViolation]
    ) -> List[AutofixResult]:
        results: List[AutofixResult] = []
        for v in violations:
            if not v.file_path or not v.file_path.exists():
                continue
            if "Missing required 'name'" not in v.message:
                continue
            # Read BOM-stripped so prepend_frontmatter_fields can match the
            # opening ``---``; the BOM/line endings are restored on write.
            original = read_text(v.file_path)
            if original is None:
                continue
            dir_name = v.file_path.parent.name
            kebab_name = _to_kebab(dir_name)
            # An empty/null value still has a `name:` key line — replace it in
            # place; prepending would produce a duplicate key on every run.
            fixed = replace_frontmatter_field(original, "name", f"name: {kebab_name}")
            if fixed is None:
                fixed = prepend_frontmatter_fields(original, [f"name: {kebab_name}"])
            if fixed is not None:
                results.append(
                    AutofixResult(
                        rule_id=self.rule_id,
                        file_path=v.file_path,
                        confidence=AutofixConfidence.SAFE,
                        original_content=original,
                        fixed_content=fixed,
                        description=f"Set name '{kebab_name}' from directory name",
                        violations_fixed=[v],
                    )
                )
        return results

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        for skill_node in context.lint_tree.find(SkillNode):
            blocks = skill_node.find(SkillBlock)
            if not blocks:
                violations.append(
                    self.violation(
                        "SKILL.md not found",
                        file_path=skill_node.path / "SKILL.md",
                    )
                )
                continue

            block = blocks[0]
            if block.frontmatter_error:
                violations.append(
                    self.violation(
                        block.frontmatter_error,
                        block=block,
                        line=block.frontmatter_error_line,
                    )
                )
                continue

            if not block.has_frontmatter:
                violations.append(
                    self.violation(
                        "Missing YAML frontmatter (must start with ---)",
                        block=block,
                    )
                )
                continue

            name = block.field_value("name")
            if not name:
                violations.append(self.violation("Missing required 'name' field", block=block))
            elif not isinstance(name, str):
                violations.append(
                    self.violation(
                        "'name' must be a string",
                        block=block,
                        line=block.key_line("name"),
                    )
                )
            elif len(name) > NAME_MAX_LENGTH:
                violations.append(
                    self.violation(
                        f"'name' exceeds {NAME_MAX_LENGTH} characters ({len(name)})",
                        block=block,
                        line=block.key_line("name"),
                    )
                )

            desc = block.field_value("description")
            if not desc:
                violations.append(
                    self.violation("Missing required 'description' field", block=block)
                )
            elif not isinstance(desc, str):
                violations.append(
                    self.violation(
                        "'description' must be a string",
                        block=block,
                        line=block.key_line("description"),
                    )
                )

            license_fld = block.field("license")
            if license_fld and not isinstance(license_fld.value, str):
                violations.append(
                    self.violation(
                        "'license' must be a string",
                        block=block,
                        line=license_fld.field_line,
                    )
                )

            compat_fld = block.field("compatibility")
            if compat_fld:
                compat = compat_fld.value
                compat_line = compat_fld.field_line
                if not isinstance(compat, str):
                    violations.append(
                        self.violation(
                            "'compatibility' must be a string",
                            block=block,
                            line=compat_line,
                        )
                    )
                elif not compat.strip():
                    violations.append(
                        self.violation(
                            "'compatibility' must not be empty if provided",
                            block=block,
                            line=compat_line,
                        )
                    )
                elif len(compat) > COMPATIBILITY_MAX_LENGTH:
                    violations.append(
                        self.violation(
                            f"'compatibility' exceeds {COMPATIBILITY_MAX_LENGTH} characters ({len(compat)})",
                            block=block,
                            line=compat_line,
                        )
                    )

            meta_fld = block.field("metadata")
            if meta_fld:
                meta = meta_fld.value
                meta_line = meta_fld.field_line
                if not isinstance(meta, dict):
                    violations.append(
                        self.violation(
                            "'metadata' must be a mapping",
                            block=block,
                            line=meta_line,
                        )
                    )
                else:
                    for k, v in meta.items():
                        if not isinstance(k, str):
                            violations.append(
                                self.violation(
                                    f"'metadata' key {k!r} must be a string",
                                    block=block,
                                    line=meta_line,
                                )
                            )

            at_fld = block.field("allowed-tools")
            if at_fld:
                at = at_fld.value
                at_line = at_fld.field_line
                if isinstance(at, list):
                    if not all(isinstance(item, str) for item in at):
                        violations.append(
                            self.violation(
                                "'allowed-tools' list items must all be strings",
                                block=block,
                                line=at_line,
                            )
                        )
                elif not isinstance(at, str):
                    violations.append(
                        self.violation(
                            "'allowed-tools' must be a string or list of strings",
                            block=block,
                            line=at_line,
                        )
                    )

            extra_required = self.config.get("required-fields", [])
            for field_name in extra_required:
                if field_name in self.BUILTIN_REQUIRED:
                    continue
                if not block.field_value(field_name):
                    fld = block.field(field_name)
                    line = fld.field_line if fld else None
                    violations.append(
                        self.violation(
                            f"Missing required field '{field_name}'",
                            block=block,
                            line=line,
                        )
                    )

            required_meta = self.config.get("required-metadata", [])
            if required_meta:
                meta = block.field_value("metadata")
                meta_line = block.key_line("metadata")
                if meta is None:
                    if "metadata" not in extra_required:
                        violations.append(
                            self.violation(
                                "Missing required 'metadata' (needed for required-metadata check)",
                                block=block,
                                line=meta_line,
                            )
                        )
                elif isinstance(meta, dict):
                    for key in required_meta:
                        val = meta.get(key)
                        if val is None or (isinstance(val, str) and not val.strip()):
                            violations.append(
                                self.violation(
                                    f"Missing required metadata key '{key}'",
                                    block=block,
                                    line=meta_line,
                                )
                            )

        return violations

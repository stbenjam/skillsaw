"""AgentSkill name format validation rule"""

import re
from typing import List

from ruamel.yaml import YAML as _RuamelYAML
from ruamel.yaml import YAMLError as _RuamelYAMLError
from ruamel.yaml.comments import CommentedMap

from skillsaw.rule import Rule, RuleViolation, AutofixResult, AutofixConfidence, Severity
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.lint_target import SkillNode
from skillsaw.rules.builtin.content_analysis import SkillBlock
from skillsaw.utils import frontmatter_text, parse_frontmatter, replace_frontmatter_field

from ._helpers import NAME_PATTERN, CONSECUTIVE_HYPHENS, _to_kebab, _add_rename


def _inline_comment(name_line: str) -> str:
    """Return the inline YAML comment on a raw ``name: ...`` line (with its
    leading whitespace), or ``""`` when there is none.

    A ``#`` inside a quoted scalar (``name: "a#b"``) is part of the value,
    so the line is parsed as YAML rather than regex-split on ``#``.
    """
    ry = _RuamelYAML()
    ry.preserve_quotes = True
    try:
        data = ry.load(name_line)
    except _RuamelYAMLError:
        return ""
    if not isinstance(data, CommentedMap):
        return ""
    tokens = data.ca.items.get("name")
    comment = tokens[2] if tokens and len(tokens) > 2 else None
    if comment is None:
        return ""
    start = comment.start_mark.column
    while start > 0 and name_line[start - 1] in " \t":
        start -= 1
    suffix = name_line[start:]
    if suffix and suffix[0] not in " \t":
        suffix = " " + suffix
    return suffix


class AgentSkillNameRule(Rule):
    """Validate skill name format per agentskills.io spec"""

    autofix_confidence = AutofixConfidence.SAFE

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

        for skill_node in context.lint_tree.find(SkillNode):
            blocks = skill_node.find(SkillBlock)
            if not blocks:
                continue
            block = blocks[0]
            if block.frontmatter_error or not block.has_frontmatter:
                continue

            name = block.field_value("name")
            if not name or not isinstance(name, str):
                continue

            name_line = block.key_line("name")

            if not NAME_PATTERN.match(name):
                violations.append(
                    self.violation(
                        f"Name '{name}' must contain only lowercase letters, numbers, and hyphens",
                        block=block,
                        line=name_line,
                    )
                )
                continue

            if name.endswith("-"):
                violations.append(
                    self.violation(
                        f"Name '{name}' must not end with a hyphen",
                        block=block,
                        line=name_line,
                    )
                )

            if CONSECUTIVE_HYPHENS.search(name):
                violations.append(
                    self.violation(
                        f"Name '{name}' must not contain consecutive hyphens",
                        block=block,
                        line=name_line,
                    )
                )

            if skill_node.path != context.root_path and name != skill_node.path.name:
                violations.append(
                    self.violation(
                        f"Name '{name}' does not match directory name '{skill_node.path.name}'",
                        block=block,
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
            # The old name must be the parsed YAML value the violation was
            # raised against — a raw-line slice would fold an inline comment
            # (``name: Deploy_Service # legacy``) into the rename manifest
            # and the kebab-cased replacement (issue #322).
            fm, _body, _err = parse_frontmatter(original)
            old_name = fm.get("name") if fm else None
            if not isinstance(old_name, str) or not old_name:
                continue
            if "does not match directory" in v.message:
                new_name = v.file_path.parent.name
            else:
                new_name = _to_kebab(old_name)
            if new_name == old_name or not NAME_PATTERN.match(new_name):
                continue
            fm_text = frontmatter_text(original) or ""
            line_match = re.search(r"^name[ \t]*:[^\r\n]*", fm_text, re.MULTILINE)
            comment = _inline_comment(line_match.group(0)) if line_match else ""
            fixed = replace_frontmatter_field(original, "name", f"name: {new_name}{comment}")
            if fixed is None:
                continue

            def _record_rename(root=context.root_path, old=old_name, new=new_name):
                _add_rename(root, old, new)

            results.append(
                AutofixResult(
                    rule_id=self.rule_id,
                    file_path=v.file_path,
                    confidence=AutofixConfidence.SAFE,
                    original_content=original,
                    fixed_content=fixed,
                    description=f"Renamed '{old_name}' to '{new_name}'",
                    violations_fixed=[v],
                    # Recording the rename is a repository state change; defer
                    # it to apply time so dry-run stays side-effect free.
                    on_apply=_record_rename,
                )
            )
        return results

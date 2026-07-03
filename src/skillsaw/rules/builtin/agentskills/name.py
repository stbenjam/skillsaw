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
from skillsaw.utils import (
    frontmatter_text,
    parse_frontmatter,
    read_text,
    replace_frontmatter_field,
)

from ._helpers import NAME_PATTERN, CONSECUTIVE_HYPHENS, _to_kebab, _add_rename


def _parse_name_line(name_line: str):
    """Parse a raw ``name: ...`` line into ``(value, comment_suffix)``.

    ``value`` is the scalar parsed from the line alone (``None`` when the
    line is not a one-line ``name`` mapping — e.g. a block-scalar indicator
    like ``name: >-`` or an empty ``name:``).  ``comment_suffix`` is the
    inline YAML comment with its leading whitespace, or ``""``.

    A ``#`` inside a quoted scalar (``name: "a#b"``) is part of the value,
    so the line is parsed as YAML rather than regex-split on ``#``.
    """
    ry = _RuamelYAML()
    ry.preserve_quotes = True
    try:
        data = ry.load(name_line)
    except _RuamelYAMLError:
        return None, ""
    if not isinstance(data, CommentedMap):
        return None, ""
    value = data.get("name")
    tokens = data.ca.items.get("name")
    comment = tokens[2] if tokens and len(tokens) > 2 else None
    if comment is None:
        return value, ""
    start = comment.start_mark.column
    while start > 0 and name_line[start - 1] in " \t":
        start -= 1
    suffix = name_line[start:]
    if suffix and suffix[0] not in " \t":
        suffix = " " + suffix
    return value, suffix


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
        return "Skill name must be lowercase letters, numbers, and hyphens and match directory name"

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
            # utils.read_text strips a UTF-8 BOM (utf-8-sig); a raw
            # read_text(encoding="utf-8") would keep the stray U+FEFF, which
            # prevents parse_frontmatter's anchored ^--- match and silently
            # skips the fix for BOM files.  write_text_preserving restores
            # the BOM at apply time.
            original = read_text(v.file_path)
            if original is None:
                continue
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
            if not line_match:
                continue
            line_value, comment = _parse_name_line(line_match.group(0))
            # The rewrite replaces exactly one line, so it is only safe when
            # the whole value lives on that line.  A block scalar
            # (``name: >-``), a value on the following line, or a duplicate
            # ``name:`` key (PyYAML is last-wins, the regex is first-match)
            # all make the line value differ from the parsed value — rewriting
            # the key line would merge the leftover continuation lines into
            # the new scalar and corrupt the frontmatter.  Skip those.
            if line_value != old_name:
                continue
            fixed = replace_frontmatter_field(original, "name", f"name: {new_name}{comment}")
            if fixed is None:
                continue
            # Convergence guard: the rewritten frontmatter must actually
            # parse to the new name (duplicate identical ``name:`` keys pass
            # the line-value check above but PyYAML still resolves to the
            # untouched later key, so the fix would churn forever).
            new_fm, _new_body, _new_err = parse_frontmatter(fixed)
            if not new_fm or new_fm.get("name") != new_name:
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

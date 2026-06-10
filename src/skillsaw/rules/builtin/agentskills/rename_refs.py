"""AgentSkill rename references rule"""

import json
import re
from pathlib import Path
from typing import Dict, List, Tuple

from skillsaw.rule import Rule, RuleViolation, AutofixResult, AutofixConfidence, Severity
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.lint_target import SkillNode
from skillsaw.markdown_doc import splice
from skillsaw.rules.builtin.content_analysis import gather_all_content_blocks

from ._helpers import (
    _read_renames_manifest,
    _write_renames_manifest,
    _RENAMES_LOCK,
)

# Characters that can be part of a skill name reference. A match is only a
# reference when the old name is not embedded in a longer name-like token:
# 'api' must not match inside 'rapid' or 'api-v2'.
_NAME_CHAR = "[A-Za-z0-9_-]"


def _name_pattern(old_name: str) -> re.Pattern:
    return re.compile(rf"(?<!{_NAME_CHAR}){re.escape(old_name)}(?!{_NAME_CHAR})")


class AgentSkillRenameRefsRule(Rule):
    """Update stale skill name references after a rename"""

    repo_types = {
        RepositoryType.AGENTSKILLS,
        RepositoryType.SINGLE_PLUGIN,
        RepositoryType.MARKETPLACE,
        RepositoryType.DOT_CLAUDE,
    }

    @property
    def rule_id(self) -> str:
        return "agentskill-rename-refs"

    @property
    def description(self) -> str:
        return "Update stale skill name references after a rename"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    @property
    def llm_fix_prompt(self):
        return (
            "A skill was renamed, and these lines still contain the old "
            "name. The old name may also be a generic term (e.g. a skill "
            "named 'api'), so judge each flagged occurrence from its "
            "surrounding text:\n"
            "- If it refers to the renamed skill, replace just that "
            "occurrence of the old name with the new name. Never modify "
            "surrounding words, and never touch text where the old name is "
            "only a substring of another word.\n"
            "- If it does NOT refer to the skill (a generic use of the "
            "term), leave the text unchanged and instead add a suppression "
            "comment on its own line directly above it:\n"
            "  <!-- skillsaw-disable-next-line agentskill-rename-refs -->\n"
            "  (in YAML files use '# skillsaw-disable-next-line "
            "agentskill-rename-refs' instead)\n"
            "- Make no other edits."
        )

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        renames = _read_renames_manifest(context.root_path)
        if not renames:
            return []

        violations = []
        old_names = {r["old"] for r in renames}
        patterns = {r["old"]: _name_pattern(r["old"]) for r in renames}
        referenced_olds: set[str] = set()

        for block in gather_all_content_blocks(context):
            try:
                content = block.path.read_text(encoding="utf-8")
            except OSError:
                continue
            lines = content.splitlines()
            for rename in renames:
                old, new = rename["old"], rename["new"]
                pattern = patterns[old]
                for line_no, line in enumerate(lines, 1):
                    if not pattern.search(line):
                        continue
                    violations.append(
                        self.violation(
                            f"Stale reference to renamed skill '{old}' " f"(renamed to '{new}')",
                            file_path=block.path,
                            line=line_no,
                        )
                    )
                    referenced_olds.add(old)

        for skill_node in context.lint_tree.find(SkillNode):
            evals_json = skill_node.path / "evals" / "evals.json"
            if not evals_json.exists():
                continue
            try:
                raw = evals_json.read_text(encoding="utf-8")
                data = json.loads(raw)
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            skill_name = data.get("skill_name")
            if isinstance(skill_name, str) and skill_name in old_names:
                rename = next(r for r in renames if r["old"] == skill_name)
                violations.append(
                    self.violation(
                        f"evals.json 'skill_name' ({skill_name!r}) references "
                        f"renamed skill (now '{rename['new']}')",
                        file_path=evals_json,
                    )
                )
                referenced_olds.add(skill_name)

        with _RENAMES_LOCK:
            current = _read_renames_manifest(context.root_path)
            still_active = [r for r in current if r["old"] in referenced_olds]
            if len(still_active) < len(current):
                _write_renames_manifest(context.root_path, still_active)

        return violations

    def fix(
        self, context: RepositoryContext, violations: List[RuleViolation]
    ) -> List[AutofixResult]:
        renames = _read_renames_manifest(context.root_path)
        if not renames:
            return []

        rename_map = {r["old"]: r["new"] for r in renames}
        patterns = {old: _name_pattern(old) for old in rename_map}
        results: List[AutofixResult] = []

        # One fix per file: group line-scoped violations so the replacement
        # is applied exactly once per file per run (idempotent — a rewritten
        # reference no longer matches the whole-name pattern).
        by_file: Dict[Path, List[RuleViolation]] = {}
        for v in violations:
            if not v.file_path or not v.file_path.exists():
                continue
            by_file.setdefault(v.file_path, []).append(v)

        for file_path, file_violations in by_file.items():
            try:
                original = file_path.read_text(encoding="utf-8")
            except OSError:
                continue

            if file_path.name == "evals.json":
                try:
                    data = json.loads(original)
                    sk = data.get("skill_name", "")
                    if sk in rename_map:
                        data["skill_name"] = rename_map[sk]
                        fixed = json.dumps(data, indent=2) + "\n"
                    else:
                        continue
                except (json.JSONDecodeError, KeyError):
                    continue
            else:
                fixed = self._fix_lines(original, file_violations, rename_map, patterns)

            if fixed == original:
                continue

            results.append(
                AutofixResult(
                    rule_id=self.rule_id,
                    file_path=file_path,
                    confidence=AutofixConfidence.SUGGEST,
                    original_content=original,
                    fixed_content=fixed,
                    description=f"Updated skill name references in {file_path.name}",
                    violations_fixed=file_violations,
                )
            )

        return results

    @staticmethod
    def _fix_lines(
        original: str,
        violations: List[RuleViolation],
        rename_map: Dict[str, str],
        patterns: Dict[str, re.Pattern],
    ) -> str:
        """Splice whole-name replacements on the violations' lines only."""
        lines = original.splitlines()
        edits: List[Tuple[int, int, int, str]] = []
        for line_no in sorted({v.line for v in violations if v.line}):
            if line_no < 1 or line_no > len(lines):
                continue
            line = lines[line_no - 1]
            for old, new in rename_map.items():
                for match in patterns[old].finditer(line):
                    edits.append((line_no, match.start(), match.end(), new))
        return splice(original, edits)

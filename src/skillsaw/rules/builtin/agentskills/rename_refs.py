"""AgentSkill rename references rule"""

import json
import re
from typing import List, Optional

from skillsaw.rule import Rule, RuleViolation, AutofixResult, AutofixConfidence, Severity
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.lint_target import SkillNode
from skillsaw.rules.builtin.content_analysis import gather_all_content_blocks

from ._helpers import (
    _read_renames_manifest,
    _write_renames_manifest,
    _RENAMES_LOCK,
)


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

    def _find_line(self, content: str, old_name: str) -> Optional[int]:
        for i, line in enumerate(content.splitlines(), 1):
            if old_name in line:
                return i
        return None

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        renames = _read_renames_manifest(context.root_path)
        if not renames:
            return []

        violations = []
        old_names = {r["old"] for r in renames}
        referenced_olds: set[str] = set()

        for block in gather_all_content_blocks(context):
            try:
                content = block.path.read_text(encoding="utf-8")
            except OSError:
                continue
            for rename in renames:
                old, new = rename["old"], rename["new"]
                if old not in content:
                    continue
                if block.path.name == "SKILL.md":
                    fm_match = re.search(r"^name:\s*(.+)$", content, re.MULTILINE)
                    if fm_match and fm_match.group(1).strip() == new:
                        body_after_fm = content[fm_match.end() :]
                        if old not in body_after_fm:
                            continue
                line = self._find_line(content, old)
                violations.append(
                    self.violation(
                        f"Stale reference to renamed skill '{old}' " f"(renamed to '{new}')",
                        file_path=block.path,
                        line=line,
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
        results: List[AutofixResult] = []

        for v in violations:
            if not v.file_path or not v.file_path.exists():
                continue

            try:
                original = v.file_path.read_text(encoding="utf-8")
            except OSError:
                continue

            if v.file_path.name == "evals.json":
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
            elif v.line:
                lines = original.splitlines(keepends=True)
                idx = v.line - 1
                if idx < 0 or idx >= len(lines):
                    continue
                line = lines[idx]
                for old, new in rename_map.items():
                    line = line.replace(old, new)
                if line == lines[idx]:
                    continue
                lines[idx] = line
                fixed = "".join(lines)
            else:
                continue

            if fixed == original:
                continue

            results.append(
                AutofixResult(
                    rule_id=self.rule_id,
                    file_path=v.file_path,
                    confidence=AutofixConfidence.SUGGEST,
                    original_content=original,
                    fixed_content=fixed,
                    description=f"Updated skill name references in {v.file_path.name}",
                    violations_fixed=[v],
                )
            )

        return results

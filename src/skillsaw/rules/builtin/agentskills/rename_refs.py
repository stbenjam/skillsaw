"""AgentSkill rename references rule"""

import json
import re
from pathlib import Path
from typing import Dict, List, Tuple

from skillsaw.rule import Rule, RuleViolation, AutofixResult, AutofixConfidence, Severity
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.lint_target import SkillNode
from skillsaw.markdown_doc import splice
from skillsaw.rules.builtin.content_analysis import (
    gather_all_content_blocks,
    patterns_matching_anywhere,
)

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

    config_schema = {
        "autofix-min-segments": {
            "type": "int",
            "default": 2,
            "description": "Minimum hyphen-separated segments in the old name for autofix to apply (single-word names are too ambiguous to fix safely)",
        },
    }

    @property
    def rule_id(self) -> str:
        return "agentskill-rename-refs"

    @property
    def description(self) -> str:
        return "Update stale skill name references after a rename"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        renames = _read_renames_manifest(context.root_path)
        if not renames:
            return []

        violations = []
        old_names = {r["old"] for r in renames}
        patterns = {r["old"]: _name_pattern(r["old"]) for r in renames}
        pattern_specs = [(patterns[r["old"]], r) for r in renames]
        referenced_olds: set[str] = set()

        # fix() skips old names below autofix-min-segments (too ambiguous to
        # rewrite), so only references to longer names are fixable. There is
        # no class-level autofix_confidence, so the SUGGEST confidence of the
        # produced fixes is declared per violation.
        min_segments = self.config.get(
            "autofix-min-segments",
            self.config_schema["autofix-min-segments"]["default"],
        )

        def _fix_kwargs(old_name: str) -> dict:
            if len(old_name.split("-")) >= min_segments:
                return {"fixable": True, "fix_confidence": AutofixConfidence.SUGGEST}
            return {"fixable": False}

        for block in gather_all_content_blocks(context):
            try:
                content = block.path.read_text(encoding="utf-8")
            except OSError:
                continue
            # Whole-text prefilter (C-speed literal check) so the per-line
            # regex loop only runs for renames actually present in the block;
            # results-identical to scanning every line with every pattern.
            active = patterns_matching_anywhere(content, pattern_specs)
            if not active:
                continue
            lines = content.splitlines()
            for pattern, rename in active:
                old, new = rename["old"], rename["new"]
                for line_no, line in enumerate(lines, 1):
                    if not pattern.search(line):
                        continue
                    violations.append(
                        self.violation(
                            f"Stale reference to renamed skill '{old}' " f"(renamed to '{new}')",
                            file_path=block.path,
                            line=line_no,
                            **_fix_kwargs(old),
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
                        **_fix_kwargs(skill_name),
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

        min_segments = self.config.get(
            "autofix-min-segments",
            self.config_schema["autofix-min-segments"]["default"],
        )
        rename_map = {
            r["old"]: r["new"] for r in renames if len(r["old"].split("-")) >= min_segments
        }
        if not rename_map:
            return []
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

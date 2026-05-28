"""AgentSkill evals validation rule"""

from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.lint_target import SkillNode
from skillsaw.rules.builtin.content_analysis import SkillBlock
from skillsaw.rules.builtin.utils import read_json


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

        for skill_node in context.lint_tree.find(SkillNode):
            skill_path = skill_node.path
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
                skill_blocks = skill_node.find(SkillBlock)
                fm_name = skill_blocks[0].field_value("name") if skill_blocks else None
                if fm_name is not None and fm_name != skill_name:
                    violations.append(
                        self.violation(
                            f"'skill_name' ({skill_name!r}) does not match "
                            f"SKILL.md name ({fm_name!r})",
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

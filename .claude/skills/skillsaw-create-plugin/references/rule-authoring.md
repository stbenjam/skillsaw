# Rule authoring reference

Full templates and requirements for skillsaw plugin rules. Read this when
implementing Step 3 of the skillsaw-create-plugin skill.

## Rule template

Each rule subclasses `skillsaw.Rule` in `src/skillsaw_<name>/rules.py`:

```python
from typing import List

from skillsaw import RepositoryContext, Rule, RuleViolation, Severity
from skillsaw.blocks import InstructionBlock


class MyFirstRule(Rule):
    """One-line summary of what this enforces."""

    config_schema = {
        "patterns": {
            "type": "list",
            "default": ["TODO"],
            "description": "Patterns to flag",
        },
    }

    @property
    def rule_id(self) -> str:
        return "my-rule-id"

    @property
    def description(self) -> str:
        return "Instruction files should not contain TODO markers"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        patterns = self.config.get("patterns", self.config_schema["patterns"]["default"])
        for block in context.lint_tree.find(InstructionBlock):
            content = block.read_body(strip_code_blocks=False)
            if content is None:
                continue
            for i, line in enumerate(content.splitlines(), start=1):
                if any(p in line for p in patterns):
                    violations.append(
                        self.violation(f"Found marker: {line.strip()}", block=block, line=i)
                    )
        return violations
```

## Requirements for every rule

- **Discover files through the lint tree** (`context.lint_tree.find(NodeType)`),
  never by walking the filesystem. Common block types from `skillsaw.blocks`:
  `InstructionBlock` (CLAUDE.md, AGENTS.md, …), `SkillBlock`, `CommandBlock`,
  `AgentBlock`, `ClaudeMdBlock`. Run `skillsaw tree` on a target repo to see
  its nodes.
- **Report a line number** on every violation traceable to a line; never
  fabricate one when it is not.
- **Pass `block=`** to `self.violation()` for content violations — line
  numbers then map to the right file lines even for YAML-embedded bodies.
- **Expose tunable settings through `config_schema`** and read them from
  `self.config`. Users configure the rule in `.skillsaw.yaml` under `rules:`
  by its rule ID, exactly like builtin rules.
- **Declare `repo_types`** when the rule only applies to certain repository
  types — the rule then activates only on matching repositories.
- **Set `default_enabled`** to control activation: the base default `"auto"`
  runs everywhere (or on matching `repo_types`/`formats` when declared);
  `default_enabled = False` makes the rule opt-in via config.
- Parse YAML with `read_yaml_commented()` from `skillsaw.utils` (preserves
  line numbers), never `yaml.safe_load()`.
- Read markdown structure (links, fences, headings) from `block.markdown`
  accessors, never hand-rolled regexes.

## Deterministic autofix

To make violations fixable by `skillsaw fix`, set `autofix_confidence` and
override `fix()`:

```python
from skillsaw import AutofixConfidence, AutofixResult


class MyFirstRule(Rule):
    autofix_confidence = AutofixConfidence.SAFE  # or SUGGEST

    def fix(self, context, violations) -> List[AutofixResult]:
        by_file = {}
        for v in violations:
            by_file.setdefault(v.file_path, []).append(v)

        results = []
        for path, file_violations in by_file.items():
            original = path.read_text(encoding="utf-8")
            lines = original.splitlines(keepends=True)
            remove = {v.file_line for v in file_violations if v.file_line}
            fixed = "".join(ln for i, ln in enumerate(lines, start=1) if i not in remove)
            if fixed != original:
                results.append(
                    AutofixResult(
                        rule_id=self.rule_id,
                        file_path=path,
                        confidence=AutofixConfidence.SAFE,
                        original_content=original,
                        fixed_content=fixed,
                        description="Removed marker lines",
                        violations_fixed=file_violations,
                    )
                )
        return results
```

Autofix requirements:

- Fixes must be **deterministic and scoped to the violation's exact location**
  (use `v.file_line`; never `str.replace()` across the whole file — it can
  match the wrong occurrence).
- Use `AutofixConfidence.SAFE` only when the fix cannot change meaning;
  otherwise use `SUGGEST` (applied only with `skillsaw fix --suggest`).
- Fixes must be idempotent: fixing already-fixed content produces no changes.
- Do not build fixes on LLM hooks — plugins provide deterministic fixes only.

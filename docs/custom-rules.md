# Custom Rules

Create custom validation rules by extending the `Rule` base class.
Custom rules use the **lint tree** — the same typed data structure that
built-in rules operate on — to discover files instead of walking the
filesystem directly.  Run `skillsaw tree` to see what nodes your repo
contains (see [Lint Tree](lint-tree.md) for details).

!!! tip "Let an LLM write your rule"
    Point your AI coding assistant at the
    [skillsaw repo](https://github.com/stbenjam/skillsaw) and
    [these docs](https://skillsaw.org), then describe what you want to
    check — it can produce a working custom rule in a single prompt.

## Example: flag TODO comments in instruction files

This rule finds every instruction file node in the tree (CLAUDE.md,
AGENTS.md, .cursorrules, etc.), reads its content, and reports a
violation for each `TODO` or `FIXME` it finds — with line numbers.
It also supports deterministic autofix to remove those lines.

```python
import re
from typing import List

from skillsaw import Rule, RuleViolation, Severity, RepositoryContext
from skillsaw import AutofixResult, AutofixConfidence
from skillsaw.blocks import InstructionBlock


class NoTodoInInstructionsRule(Rule):
    """Instruction files should not contain TODO/FIXME comments."""

    autofix_confidence = AutofixConfidence.SAFE

    @property
    def rule_id(self) -> str:
        return "no-todo-instructions"

    @property
    def description(self) -> str:
        return "Instruction files should not contain TODO/FIXME comments"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        pattern = re.compile(r"\bTODO\b|\bFIXME\b")

        for block in context.lint_tree.find(InstructionBlock):
            content = block.read_body(strip_code_blocks=False)
            if content is None:
                continue
            for i, line in enumerate(content.splitlines(), start=1):
                if pattern.search(line):
                    violations.append(
                        self.violation(
                            f"Found TODO/FIXME: {line.strip()}",
                            file_path=block.path,
                            line=i,
                        )
                    )
        return violations

    def fix(
        self,
        context: RepositoryContext,
        violations: List[RuleViolation],
    ) -> List[AutofixResult]:
        by_file = {}
        for v in violations:
            by_file.setdefault(v.file_path, []).append(v)

        results = []
        for path, file_violations in by_file.items():
            original = path.read_text(encoding="utf-8")
            lines = original.splitlines(keepends=True)
            remove = {v.line for v in file_violations if v.line}
            fixed = "".join(
                ln for i, ln in enumerate(lines, start=1) if i not in remove
            )
            if fixed != original:
                results.append(
                    AutofixResult(
                        rule_id=self.rule_id,
                        file_path=path,
                        confidence=AutofixConfidence.SAFE,
                        original_content=original,
                        fixed_content=fixed,
                        description="Removed TODO/FIXME lines",
                        violations_fixed=file_violations,
                    )
                )
        return results
```

Then reference it in `.skillsaw.yaml`:

```yaml
custom-rules:
  - ./no_todo_instructions.py

rules:
  no-todo-instructions:
    enabled: true
    severity: warning
```

### Key concepts

| Concept | What the example shows |
|---|---|
| **Tree discovery** | `context.lint_tree.find(InstructionBlock)` returns only instruction-file nodes — no manual glob needed. |
| **Node types** | Import the block type you need from `skillsaw.blocks`. Common types: `InstructionBlock`, `ClaudeMdBlock`, `CommandBlock`, `SkillBlock`, `AgentBlock`. |
| **Reading content** | `block.read_body()` returns the file body. Use `strip_code_blocks=False` when you need the raw text. |
| **Line numbers** | Report `line=` on every violation so users can jump to the exact location. |
| **Autofix** | Override `fix()` and return `AutofixResult` objects. Set `autofix_confidence` on the class and match it in each result. |

For the full list of node types, see `skillsaw.lint_target` (structural nodes like `PluginNode`, `SkillNode`) and `skillsaw.blocks` (content blocks). The block types are also still re-exported from `skillsaw.rules.builtin.content_analysis` for backward compatibility.

## Configuration

Custom rules can accept user-configurable parameters via `config_schema`:

```python
class NoTodoInInstructionsRule(Rule):
    config_schema = {
        "patterns": {
            "type": "list",
            "default": ["TODO", "FIXME"],
            "description": "Patterns to flag in instruction files",
        },
    }

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        patterns = self.config.get("patterns", self.config_schema["patterns"]["default"])
        pattern = re.compile("|".join(rf"\b{p}\b" for p in patterns))
        # ... rest of check logic
```

```yaml
rules:
  no-todo-instructions:
    enabled: true
    patterns: ["TODO", "FIXME", "HACK", "XXX"]
```

## More examples

For a more complete example — including a config schema, promptfoo eval
validation, and test fixtures — see the
[`examples/custom-rules/`](https://github.com/stbenjam/skillsaw/tree/main/examples/custom-rules)
directory.

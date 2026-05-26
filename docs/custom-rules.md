# Custom Rules

Create custom validation rules by extending the `Rule` base class:

```python
from pathlib import Path
from typing import List
from skillsaw import Rule, RuleViolation, Severity, RepositoryContext

class NoTodoCommentsRule(Rule):
    @property
    def rule_id(self) -> str:
        return "no-todo-comments"

    @property
    def description(self) -> str:
        return "Command files should not contain TODO comments"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        for plugin_path in context.plugins:
            commands_dir = plugin_path / "commands"
            if not commands_dir.exists():
                continue
            for cmd_file in commands_dir.glob("*.md"):
                content = cmd_file.read_text()
                if "TODO" in content:
                    violations.append(
                        self.violation("Found TODO comment", file_path=cmd_file)
                    )
        return violations
```

Then reference it in `.skillsaw.yaml`:

```yaml
custom-rules:
  - ./my_custom_rules.py

rules:
  no-todo-comments:
    enabled: true
    severity: warning
```

For a more complete example — including config schemas, promptfoo eval validation, and test fixtures — see the [`examples/custom-rules/`](https://github.com/stbenjam/skillsaw/tree/main/examples/custom-rules) directory.

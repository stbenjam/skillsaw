"""File inventory for the Claude rules directory's structural checks."""

from dataclasses import dataclass

from skillsaw.lint_target import LintTarget


@dataclass(eq=False)
class ClaudeRuleFileNode(LintTarget):
    """A Claude rules file, including extensions the consumer does not load.

    Markdown prose and frontmatter retain their independent PluginRuleBlock.
    This inventory does not expose unloaded files as instruction content.
    """

    def tree_label(self) -> str:
        return f"{self.path.name} (Claude rule validation)"

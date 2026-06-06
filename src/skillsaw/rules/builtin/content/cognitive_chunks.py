"""Content cognitive chunks rule"""

from typing import List

from skillsaw.rule import AutofixConfidence, Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.content_analysis import (
    gather_all_content_blocks,
    _HEADING_RE,
)


class ContentCognitiveChunksRule(Rule):
    """Check section organization for cognitive chunking"""

    autofix_confidence = AutofixConfidence.LLM

    formats = None
    since = "0.7.0"

    @property
    def rule_id(self) -> str:
        return "content-cognitive-chunks"

    @property
    def description(self) -> str:
        return "Check that instruction files are organized into cognitive chunks with headings"

    def default_severity(self) -> Severity:
        return Severity.INFO

    @property
    def llm_fix_prompt(self):
        return (
            "You are reorganizing AI coding assistant instruction files for "
            "better cognitive chunking. Add section headings to organize "
            "instructions into logical groups.\n\n"
            "Rules:\n"
            "- Add descriptive markdown headings to group related instructions\n"
            "- Use ## for top-level sections, ### for subsections\n"
            "- Group by task or domain (e.g., '## Testing', '## Code Style')\n"
            "- Aim for 10-30 lines per section\n"
            "- Do NOT change the content of the instructions\n"
            "- Preserve markdown formatting"
        )

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        for cf in gather_all_content_blocks(context):
            body = cf.read_body()
            if not body or len(body.strip()) < 100:
                continue
            lines = body.splitlines()
            headings = [l for l in lines if _HEADING_RE.match(l)]

            if not headings and len(lines) > 10:
                violations.append(
                    self.violation(
                        "No headings in instruction file — add section headings for cognitive chunking",
                        block=cf,
                    )
                )
                continue

            if len(headings) == 1 and len(lines) > 30:
                violations.append(
                    self.violation(
                        "All content under a single heading — break into task-organized sections",
                        block=cf,
                    )
                )
        return violations

"""Content section length rule"""

from typing import List

from skillsaw.rule import AutofixConfidence, Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.content_analysis import (
    gather_all_content_blocks,
    _HEADING_RE,
)


class ContentSectionLengthRule(Rule):
    """Warn about overly long markdown sections"""

    autofix_confidence = AutofixConfidence.LLM

    formats = None
    since = "0.7.0"

    _DEFAULT_MAX_TOKENS = 500
    _CHARS_PER_TOKEN = 4

    config_schema = {
        "max-tokens": {
            "type": "int",
            "default": 500,
            "description": "Maximum estimated tokens per section before triggering a warning",
        },
    }

    @property
    def rule_id(self) -> str:
        return "content-section-length"

    @property
    def description(self) -> str:
        max_tokens = self.config.get("max-tokens", self._DEFAULT_MAX_TOKENS)
        return f"Warn about markdown sections longer than ~{max_tokens} tokens"

    def default_severity(self) -> Severity:
        return Severity.INFO

    @property
    def llm_fix_prompt(self):
        return (
            "You are reorganizing AI coding assistant instruction files. "
            "Long sections should be broken into smaller, "
            "focused subsections.\n\n"
            "Rules:\n"
            "- Split long sections into smaller subsections with descriptive headings\n"
            "- Group related instructions under the same subsection\n"
            "- Use one heading level deeper than the parent section\n"
            "- Do NOT change the content of the instructions\n"
            "- Preserve markdown formatting"
        )

    @classmethod
    def _estimate_tokens(cls, text: str) -> int:
        return max(1, len(text) // cls._CHARS_PER_TOKEN)

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        max_tokens = self.config.get("max-tokens", self._DEFAULT_MAX_TOKENS)
        violations = []
        for cf in gather_all_content_blocks(context):
            body = cf.read_body()
            if not body:
                continue
            lines = body.splitlines()
            sections: List[tuple] = []
            current_heading_line = 1
            current_heading_text = "(top of file)"
            section_start = 0

            for i, line in enumerate(lines):
                m = _HEADING_RE.match(line)
                if m:
                    if i > section_start:
                        sections.append(
                            (current_heading_text, current_heading_line, section_start, i)
                        )
                    current_heading_text = m.group(2)
                    current_heading_line = i + 1
                    section_start = i + 1

            if len(lines) > section_start:
                sections.append(
                    (current_heading_text, current_heading_line, section_start, len(lines))
                )

            for heading, heading_line, start, end in sections:
                section_text = "\n".join(lines[start:end])
                token_count = self._estimate_tokens(section_text)
                if token_count > max_tokens:
                    violations.append(
                        self.violation(
                            f"Section '{heading}' is ~{token_count} tokens (max recommended: {max_tokens})",
                            block=cf,
                            line=heading_line if heading_line > 0 else None,
                        )
                    )
        return violations

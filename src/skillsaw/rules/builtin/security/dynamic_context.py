"""Security rule for dynamic context injection in agent-facing content.

Some agent clients expand dynamic-context markers — an inline code span
prefixed with ``!``, or a fenced block whose info string starts with ``!`` —
by executing their contents before agent-facing content is sent to the
model.  That turns otherwise prompt-only content into a shell execution
surface, so this rule requires every such command in agent-facing content to
be explicitly allowlisted.
"""

from typing import List, Set, Tuple

from skillsaw.context import RepositoryContext
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.rules.builtin.content_analysis import gather_all_content_blocks

DynamicContextMatch = Tuple[int, str, str, str]


class SecurityDynamicContextRule(Rule):
    """Require explicit approval for dynamic context commands in agent content."""

    default_enabled = "auto"

    formats = None
    repo_types = None
    since = "0.19.0"

    config_schema = {
        "allowlist": {
            "type": "list",
            "default": [],
            "description": (
                "Dynamic-context commands to permit (exact match; "
                "multi-line fenced commands may be one YAML block scalar)"
            ),
        },
    }

    @property
    def rule_id(self) -> str:
        return "security-dynamic-context"

    @property
    def description(self) -> str:
        return (
            "Require an allowlist for dynamic context commands that execute "
            "shell code while loading agent context"
        )

    def default_severity(self) -> Severity:
        # Dynamic context is a documented, first-party feature with a high
        # legitimate base rate, so the auto-enabled default must not fail
        # previously-clean CI runs. Repos that want a hard gate raise this
        # to error (or run with --fail-level warning).
        return Severity.WARNING

    def _allowlist(self) -> Set[str]:
        configured = self.config.get("allowlist", [])
        if not isinstance(configured, list):
            return set()
        return {command for command in configured if isinstance(command, str) and command}

    @staticmethod
    def _inline_matches(block) -> List[DynamicContextMatch]:
        """Return inline dynamic-context spans in *block*.

        ``MarkdownDoc`` supplies the code-span position.  The established
        syntax expands the inline form when the marker is at the start of a
        line or follows whitespace, so ``KEY=!`command``` remains ordinary
        text.
        """
        doc = block.markdown
        matches: List[DynamicContextMatch] = []
        for span in doc.code_spans():
            if span.col_start is None:
                # A fenced form is the portable representation for
                # multi-line commands; an inline code span without a
                # trustworthy column cannot be classified safely.
                continue
            line = doc.line(span.body_line)
            marker = span.col_start - 1
            if marker < 0 or marker >= len(line) or line[marker] != "!":
                continue
            if marker > 0 and not line[marker - 1].isspace():
                continue
            command = span.content
            if command:
                matches.append((span.body_line, command, "inline", f"inline:{marker}"))
        return matches

    @staticmethod
    def _fenced_matches(block) -> List[DynamicContextMatch]:
        """Return `` ```! `` fenced dynamic-context blocks in *block*."""
        doc = block.markdown
        matches: List[DynamicContextMatch] = []
        for fence in doc.fences():
            # Any info string starting with "!" is treated as executable so
            # a client matching loosely (e.g. ```!bash) cannot slip past a
            # rule that required exactly "!".
            if fence.indented or not fence.info.startswith("!"):
                continue
            # MarkdownDoc exposes parser-normalized fence content, which
            # removes blockquote/list prefixes and includes the final command
            # line even when the fence is unterminated. Remove only the one
            # structural trailing newline; blank lines and horizontal
            # whitespace are part of exact allowlist matching.
            command = fence.content.removesuffix("\n")
            if command:
                matches.append(
                    (
                        fence.body_line_start,
                        command,
                        "fenced",
                        # Content-based so baselined findings survive
                        # unrelated edits above the fence.
                        f"fenced:{command}",
                    )
                )
        return matches

    def _violation_message(self, command: str, kind: str, allowlist: Set[str]) -> str:
        if allowlist:
            prefix = "Non-allowlisted dynamic context"
        else:
            prefix = "Dynamic context is prohibited"
        form = "command" if kind == "inline" else "command block"
        return (
            f"{prefix} {form}: {command!r} — it executes shell code before "
            "the agent sees this content; remove it or add the exact command "
            "to the rule's allowlist"
        )

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        allowlist = self._allowlist()
        violations: List[RuleViolation] = []

        for block in gather_all_content_blocks(context):
            body = block.read_body(strip_code_blocks=False)
            if not body or "!" not in body:
                continue

            matches = self._inline_matches(block) + self._fenced_matches(block)
            for line, command, kind, discriminator in sorted(matches, key=lambda match: match[0]):
                if command in allowlist:
                    continue
                violations.append(
                    self.violation(
                        self._violation_message(command, kind, allowlist),
                        block=block,
                        line=line,
                        fingerprint_discriminator=discriminator,
                    )
                )
        return violations

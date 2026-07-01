"""Content actionability score rule"""

import re
from collections import defaultdict
from typing import Dict, List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.content_analysis import (
    gather_all_content_blocks,
)


class ContentActionabilityScoreRule(Rule):
    """Compute an actionability score for instruction files"""

    formats = None
    since = "0.7.0"
    baseline_mode = "floor"

    _VERB_WORDS = frozenset(
        "use run create add remove check set write read call return throw "
        "avoid prefer include exclude follow implement test validate verify "
        "handle log format configure install update delete move copy import "
        "export define declare initialize override extend wrap deploy build "
        "commit push pull merge rebase review ensure make keep always never".split()
    )
    _VERB_RE = re.compile(
        r"\b(?:" + "|".join(sorted(_VERB_WORDS)) + r")\b",
        re.IGNORECASE,
    )
    _COMMAND_RE = re.compile(r"`[^`]+`")
    _PATH_RE = re.compile(r"(?:`[^`]*[/\\][^`]*`|[\w./\\]+\.\w{1,5})")
    WARN_THRESHOLD = 40

    _WORD_RE = re.compile(r"\w+")

    def _has_verb(self, line: str) -> bool:
        """Equivalent to ``_VERB_RE.search(line)`` as a boolean.

        The pattern is a \\b-delimited alternation of plain words, so it
        matches a line iff one of the words appears as a complete ``\\w+``
        token — a frozenset intersection is much faster than running the
        50-branch alternation at every character position.
        """
        return not self._VERB_WORDS.isdisjoint(self._WORD_RE.findall(line.lower()))

    @property
    def rule_id(self) -> str:
        return "content-actionability-score"

    @property
    def description(self) -> str:
        return "Score instruction files on actionability (verb density, commands, file references)"

    def default_severity(self) -> Severity:
        return Severity.INFO

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        for cf in gather_all_content_blocks(context):
            if not cf.read_body(strip_code_blocks=False):
                continue
            doc = cf.markdown
            # Code spans are blanked in prose, but commands and backticked
            # paths count toward actionability — rebuild each line from its
            # prose text plus the code spans the AST located on it.
            spans_by_line: Dict[int, List[str]] = defaultdict(list)
            for span in doc.code_spans():
                spans_by_line[span.body_line].append(span.content)
            lines: List[str] = []
            for body_line, prose in enumerate((text for _, text in doc.prose_lines()), 1):
                rebuilt = prose
                for span_content in spans_by_line.get(body_line, []):
                    rebuilt += f" `{span_content}`"
                if rebuilt.strip():
                    lines.append(rebuilt)
            if len(lines) < 5:
                continue
            total = len(lines)
            verb_lines = sum(1 for line in lines if self._has_verb(line))
            # Cheap substring prescans: _COMMAND_RE needs a backtick, _PATH_RE
            # needs a dot or a backtick — most prose lines have neither.
            cmd_lines = sum(1 for line in lines if "`" in line and self._COMMAND_RE.search(line))
            path_lines = sum(
                1 for line in lines if ("." in line or "`" in line) and self._PATH_RE.search(line)
            )

            verb_ratio = verb_lines / total
            cmd_ratio = cmd_lines / total
            path_ratio = path_lines / total
            score = int((verb_ratio * 50) + (cmd_ratio * 30) + (path_ratio * 20))
            score = min(100, score)

            if score < self.WARN_THRESHOLD:
                violations.append(
                    self.violation(
                        f"Low actionability score: {score}/100 (verbs: {verb_ratio:.0%}, commands: {cmd_ratio:.0%}, paths: {path_ratio:.0%})",
                        block=cf,
                        value=score,
                    )
                )
        return violations

"""Content unlinked internal reference rule"""

import re
from collections import defaultdict
from pathlib import Path, PurePath
from typing import Dict, List

from skillsaw.rule import AutofixConfidence, FixOp, Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.content_analysis import (
    gather_all_content_blocks,
    is_inside_inline_code,
    inline_code_span_bounds,
)


class ContentUnlinkedInternalReferenceRule(Rule):
    """Detect bare path-like strings that are not wrapped in markdown link syntax"""

    autofix_confidence = AutofixConfidence.SAFE
    formats = None
    since = "0.9.0"
    repo_types = None

    config_schema = {
        "patterns": {
            "type": "list",
            "default": ["./**/*.*", "references/**/*.md"],
            "description": "Glob patterns for path-like strings to flag when unlinked",
        },
    }

    # Match path-like strings: contain / and a file extension, or start with ./
    _PATH_LIKE_RE = re.compile(
        r"(?<!\()"  # not preceded by ( (would be inside link syntax)
        r"(?:"
        r"\./[\w./_-]+"  # starts with ./
        r"|"
        r"[\w._-]+(?:/[\w._-]+)+\.[\w]{1,10}"  # contains / and has extension
        r")"
        r"(?!\))"  # not followed by ) (would be inside link syntax)
    )

    # Detect if a match is inside a markdown link [text](path)
    _LINK_SYNTAX_RE = re.compile(r"\[[^\]]*\]\([^)]*\)")

    # Detect URLs so we can skip path-like fragments inside them
    _URL_RE = re.compile(r"https?://[^\s)]+")

    @property
    def rule_id(self) -> str:
        return "content-unlinked-internal-reference"

    @property
    def description(self) -> str:
        return "Detect bare path-like strings not wrapped in markdown link syntax"

    def default_severity(self) -> Severity:
        return Severity.INFO

    def _is_inside_link(self, line: str, match_start: int, match_end: int) -> bool:
        """Check if a match position falls inside markdown link syntax."""
        for link_match in self._LINK_SYNTAX_RE.finditer(line):
            if link_match.start() <= match_start and match_end <= link_match.end():
                return True
        return False

    def _is_inside_url(self, line: str, match_start: int, match_end: int) -> bool:
        """Check if a match position falls inside a URL."""
        for url_match in self._URL_RE.finditer(line):
            if url_match.start() <= match_start and match_end <= url_match.end():
                return True
        return False

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        root = context.root_path.resolve()
        patterns = self.config.get("patterns", self.config_schema["patterns"]["default"])
        violations = []
        for cf in gather_all_content_blocks(context):
            body = cf.read_body(strip_code_blocks=True)
            if not body:
                continue
            for line_num, line in enumerate(body.splitlines(), 1):
                if not line.strip():
                    continue
                if re.match(r"^\s*@\S", line):
                    continue
                for match in self._PATH_LIKE_RE.finditer(line):
                    path_str = match.group(0)
                    if self._is_inside_link(line, match.start(), match.end()):
                        continue
                    if self._is_inside_url(line, match.start(), match.end()):
                        continue
                    if is_inside_inline_code(line, match.start(), match.end()):
                        continue
                    if not any(PurePath(path_str).match(p) for p in patterns):
                        continue
                    resolved = (cf.path.parent / path_str).resolve()
                    file_exists = False
                    try:
                        resolved.relative_to(root)
                        file_exists = resolved.exists()
                    except ValueError:
                        pass
                    msg = f"Unlinked path reference: '{path_str}' — consider wrapping in link syntax [{path_str}]({path_str})"
                    if file_exists:
                        msg += " (file exists, autofixable)"
                    violations.append(self.violation(msg, block=cf, line=line_num))
        return violations

    def fix(
        self, context: RepositoryContext, violations: List[RuleViolation], **kwargs: object
    ) -> List[FixOp]:
        fixes_by_block: Dict[int, List[tuple]] = defaultdict(list)
        block_map: Dict[int, object] = {}
        for v in violations:
            if not v.block or "autofixable" not in v.message:
                continue
            path_str = v.message.split("'")[1]
            key = id(v.block)
            fixes_by_block[key].append((path_str, v))
            block_map[key] = v.block

        results: List[FixOp] = []
        for key, replacements in fixes_by_block.items():
            block = block_map[key]
            body = block.read_body(strip_code_blocks=False)
            if body is None:
                continue
            lines = body.splitlines(True)
            violations_fixed = []
            for path_str, v in replacements:
                if v.line is None:
                    continue
                idx = v.line - 1
                if idx < 0 or idx >= len(lines):
                    continue
                line = lines[idx]
                pos = 0
                while pos < len(line):
                    loc = line.find(path_str, pos)
                    if loc == -1:
                        break
                    end = loc + len(path_str)
                    if (
                        not self._is_inside_link(line, loc, end)
                        and not self._is_inside_url(line, loc, end)
                        and not is_inside_inline_code(line, loc, end)
                    ):
                        bounds = inline_code_span_bounds(line, loc, end)
                        if bounds:
                            bt = line[bounds[0] : loc]
                            replacement = f"[{bt}{path_str}{bt}]({path_str})"
                            lines[idx] = line[: bounds[0]] + replacement + line[bounds[1] :]
                        else:
                            lines[idx] = line[:loc] + f"[{path_str}]({path_str})" + line[end:]
                        violations_fixed.append(v)
                        break
                    pos = end
            fixed_body = "".join(lines)
            if fixed_body != body:
                results.append(self.body_fix(
                    block=block,
                    original_body=body,
                    fixed_body=fixed_body,
                    description=f"Wrap {len(violations_fixed)} bare path(s) in markdown link syntax",
                    violations=violations_fixed,
                ))
        return results

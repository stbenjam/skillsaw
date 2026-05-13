"""
Content intelligence rules — analyze instruction file quality.

These rules use shared analyzers from content_analysis.py and apply to ALL
instruction file formats equally.
"""

import difflib
import os
import re
from collections import defaultdict
from pathlib import Path, PurePath
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

from skillsaw.rule import AutofixConfidence, AutofixResult, Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.rules.builtin.utils import read_text
from skillsaw.rules.builtin.content_analysis import (
    gather_all_content_blocks,
    ContentBlock,
    SkillRefBlock,
    WeakLanguageDetector,
    TautologicalDetector,
    CriticalPositionAnalyzer,
    RedundancyDetector,
    InstructionBudgetAnalyzer,
    _HEADING_RE,
    _TAUTOLOGICAL_PHRASES,
    _strip_fenced_code_blocks,
)


class ContentWeakLanguageRule(Rule):
    """Detect hedging, vague, and non-actionable language in instruction files"""

    formats = None
    since = "0.7.0"

    @property
    def rule_id(self) -> str:
        return "content-weak-language"

    @property
    def description(self) -> str:
        return "Detect hedging, vague, and non-actionable language in instruction files"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    @property
    def llm_fix_prompt(self):
        return (
            "You are a technical writing assistant fixing AI coding assistant "
            "instruction files. Your job is to replace weak, hedging language "
            "with direct, actionable instructions.\n\n"
            "Rules:\n"
            "- Replace 'try to X' with 'X'\n"
            "- Replace 'consider doing X' with 'do X' or remove the line\n"
            "- Replace 'if possible' with explicit conditions\n"
            "- Replace vague adverbs (properly, correctly, appropriately) "
            "with specific behavior\n"
            "- Do NOT change the meaning or intent of the instruction\n"
            "- Do NOT add new instructions\n"
            "- Preserve markdown formatting"
        )

    _REFERENCE_BLOCK_TYPES = (SkillRefBlock,)

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        detector = WeakLanguageDetector()
        for cf in gather_all_content_blocks(context):
            is_reference = isinstance(cf, self._REFERENCE_BLOCK_TYPES)
            for match in detector.analyze(cf):
                violations.append(
                    self.violation(
                        f"Weak language ({match.category}): '{match.phrase}' — {match.suggested_fix}",
                        block=cf,
                        line=match.line,
                        severity=Severity.INFO if is_reference else None,
                    )
                )
        return violations


class ContentTautologicalRule(Rule):
    """Detect tautological instructions that waste instruction budget"""

    formats = None
    since = "0.7.0"

    @property
    def rule_id(self) -> str:
        return "content-tautological"

    @property
    def description(self) -> str:
        return "Detect tautological instructions that the model already follows by default"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    @property
    def llm_fix_prompt(self):
        return (
            "You are fixing AI coding assistant instruction files. Remove "
            "tautological instructions that the AI model already follows "
            "by default (e.g., 'write clean code', 'follow best practices', "
            "'use meaningful variable names').\n\n"
            "Rules:\n"
            "- Remove lines that state something the model does by default\n"
            "- If the line is in a list, remove the list item\n"
            "- If removing leaves an empty section, remove the section heading too\n"
            "- Do NOT remove instructions that add project-specific constraints\n"
            "- Preserve markdown formatting"
        )

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        detector = TautologicalDetector()
        for cf in gather_all_content_blocks(context):
            for match in detector.analyze(cf):
                violations.append(
                    self.violation(
                        f"Tautological: '{match.phrase}' — {match.reason}",
                        block=cf,
                        line=match.line,
                    )
                )
        return violations


class ContentCriticalPositionRule(Rule):
    """Detect critical instructions buried in the attention dead zone"""

    formats = None
    since = "0.7.0"

    _DEFAULT_MIN_LINES = 50

    config_schema = {
        "min-lines": {
            "type": "int",
            "default": 50,
            "description": "Minimum file length (in lines) before the rule activates",
        },
    }

    @property
    def rule_id(self) -> str:
        return "content-critical-position"

    @property
    def description(self) -> str:
        return "Detect critical instructions in the middle of files where LLM attention is lowest"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    @property
    def llm_fix_prompt(self):
        return (
            "You are reorganizing AI coding assistant instruction files to "
            "improve LLM attention. Critical instructions (IMPORTANT, MUST, "
            "NEVER, ALWAYS, CRITICAL, WARNING, REQUIRED) should be in the "
            "first 20% or last 20% of the file.\n\n"
            "Rules:\n"
            "- Move flagged critical instructions to the top or bottom of the file\n"
            "- Prefer moving to the top when the instruction is a constraint\n"
            "- Prefer moving to the bottom when it's a reminder or checklist item\n"
            "- Preserve section structure — move the whole section if needed\n"
            "- Do NOT change the content of the instructions\n"
            "- Preserve markdown formatting"
        )

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        min_lines = self.config.get("min-lines", self._DEFAULT_MIN_LINES)
        analyzer = CriticalPositionAnalyzer(min_lines=min_lines)
        for cf in gather_all_content_blocks(context):
            for issue in analyzer.analyze(cf):
                violations.append(
                    self.violation(
                        f"'{issue.keyword}' instruction at line {issue.line} is in the attention dead zone (20-80%) — {issue.suggested_position}",
                        block=cf,
                        line=issue.line,
                    )
                )
        return violations


class ContentRedundantWithToolingRule(Rule):
    """Detect instructions that duplicate existing tooling configuration"""

    formats = None
    since = "0.7.0"

    @property
    def rule_id(self) -> str:
        return "content-redundant-with-tooling"

    @property
    def description(self) -> str:
        return "Detect instructions that duplicate .editorconfig, ESLint, Prettier, or tsconfig settings"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    @property
    def llm_fix_prompt(self):
        return (
            "You are fixing AI coding assistant instruction files. Remove "
            "instructions that duplicate settings already enforced by tooling "
            "config files (.editorconfig, .eslintrc, .prettierrc, tsconfig.json).\n\n"
            "Rules:\n"
            "- Remove lines that restate what a config file already enforces\n"
            "- If the line is in a list, remove the list item\n"
            "- If removing leaves an empty section, remove the section heading too\n"
            "- Do NOT remove instructions that go beyond what the config enforces\n"
            "- Preserve markdown formatting"
        )

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        detector = RedundancyDetector()
        for cf in gather_all_content_blocks(context):
            for match in detector.analyze(cf, context.root_path):
                violations.append(
                    self.violation(
                        f"Redundant with {match.existing_config_file} ({match.config_value}): '{match.instruction}'",
                        block=cf,
                        line=match.line,
                    )
                )
        return violations


class ContentInstructionBudgetRule(Rule):
    """Check total instruction count across all instruction files"""

    formats = None
    since = "0.7.0"

    @property
    def rule_id(self) -> str:
        return "content-instruction-budget"

    @property
    def description(self) -> str:
        return "Check if instruction count in a file exceeds LLM instruction budget (~150)"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    @property
    def llm_fix_prompt(self):
        return (
            "You are reducing the instruction count in an AI coding assistant "
            "instruction file. The number of imperative instructions in this "
            "file exceeds the recommended budget.\n\n"
            "Rules:\n"
            "- Merge duplicate or near-duplicate instructions\n"
            "- Remove tautological instructions the model follows by default\n"
            "- Consolidate related instructions into fewer, more precise ones\n"
            "- Prefer removing vague instructions over specific ones\n"
            "- Do NOT remove project-specific constraints or requirements\n"
            "- Preserve markdown formatting"
        )

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        content_files = gather_all_content_blocks(context)
        if not content_files:
            return []
        analyzer = InstructionBudgetAnalyzer()
        violations = []
        for cf in content_files:
            budget = analyzer.analyze_file(cf)
            if budget.total_count >= 120:
                sev = Severity.ERROR if budget.over_budget else Severity.WARNING
                msg = (
                    f"Instruction budget: {budget.total_count}/{analyzer.BUDGET} instructions "
                    f"({budget.budget_remaining} remaining)"
                )
                violations.append(self.violation(msg, block=cf, severity=sev))
            elif budget.total_count >= 80:
                msg = (
                    f"Instruction budget: {budget.total_count}/{analyzer.BUDGET} instructions "
                    f"— approaching limit"
                )
                violations.append(self.violation(msg, block=cf, severity=Severity.INFO))
        return violations


class ContentNegativeOnlyRule(Rule):
    """Detect 'never/don't/avoid X' without a positive alternative"""

    formats = None
    since = "0.7.0"

    _NEGATIVE_RE = re.compile(
        r"(?:never\s+use|don'?t\s+use|avoid\s+using|do\s+not\s+use|never\s+do|don'?t\s+do)\s+",
        re.IGNORECASE,
    )
    _POSITIVE_RE = re.compile(
        r"(?:"
        r"\binstead\b"
        r"|instead\s*,?\s+use"
        r"|prefer\s+\S+"
        r"|replace\s+with"
        r"|\buse\s+\S+"
        r"|\bapply\s+\S+"
        r"|\bset\s+\S+"
        r"|\bchoose\s+\S+"
        r"|\bswitch\s+to\b"
        r"|\bopt\s+for\b"
        r"|\brather\s+than\b"
        r"|\balways\b"
        r"|\bfollow\s+\S+"
        r"|\badd\s+\S+"
        r"|\bgenerate\s+\S+"
        r"|\bsummarize\s+\S+"
        r")",
        re.IGNORECASE,
    )
    _SCOPE_BOUNDARY_RE = re.compile(
        r"(?:don[''’]?t|do\s+not)\s+use\b.*\bwhen\s*[:*]",
        re.IGNORECASE,
    )

    @property
    def rule_id(self) -> str:
        return "content-negative-only"

    @property
    def description(self) -> str:
        return "Detect prohibitions without a positive alternative (agent has no path forward)"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    @property
    def llm_fix_prompt(self):
        return (
            "You are fixing AI coding assistant instruction files. Rewrite "
            'negative-only instructions ("don\'t do X", "never use X", '
            '"avoid X") to include a positive alternative.\n\n'
            "Rules:\n"
            "- Keep the prohibition but add what to do instead\n"
            "- Example: 'Don't use var' → 'Use const or let instead of var'\n"
            "- Example: 'Never commit secrets' → 'Store secrets in environment "
            "variables, never commit them to the repository'\n"
            "- Infer the positive alternative from context\n"
            "- Do NOT change the meaning of the prohibition\n"
            "- Preserve markdown formatting"
        )

    def _has_positive_alternative(self, line, lines, line_idx):
        neg_match = self._NEGATIVE_RE.search(line)
        if not neg_match:
            return False

        text_before_neg = line[: neg_match.start()]
        if self._POSITIVE_RE.search(text_before_neg):
            return True

        text_after_neg = line[neg_match.end() :]
        if self._POSITIVE_RE.search(text_after_neg):
            return True

        start = max(0, line_idx - 2)
        end = min(len(lines), line_idx + 5)
        for j in range(start, end):
            if j == line_idx:
                continue
            if self._POSITIVE_RE.search(lines[j]):
                return True

        return False

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        for cf in gather_all_content_blocks(context):
            body = cf.read_body()
            if not body:
                continue
            lines = body.splitlines()
            for i, line in enumerate(lines):
                stripped = line.lstrip()
                if stripped.startswith("#"):
                    continue
                if not self._NEGATIVE_RE.search(line):
                    continue
                if self._SCOPE_BOUNDARY_RE.search(line):
                    continue
                if not self._has_positive_alternative(line, lines, i):
                    violations.append(
                        self.violation(
                            f"Negative-only instruction without alternative: '{line.strip()[:80]}'",
                            block=cf,
                            line=i + 1,
                        )
                    )
        return violations


class ContentSectionLengthRule(Rule):
    """Warn about overly long markdown sections"""

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


class ContentContradictionRule(Rule):
    """Detect likely contradictions within instruction files"""

    formats = None
    since = "0.7.0"

    @property
    def llm_fix_prompt(self):
        return (
            "You are fixing AI coding assistant instruction files that contain "
            "contradictory instructions. Resolve contradictions by choosing the "
            "more specific or more useful instruction.\n\n"
            "Rules:\n"
            "- When two instructions conflict, keep the more specific one\n"
            "- If both are valid in different contexts, add context qualifiers\n"
            "- Example: 'move fast' + 'write comprehensive tests' → "
            "'Write focused tests for critical paths'\n"
            "- Do NOT remove instructions that aren't contradictory\n"
            "- Preserve markdown formatting"
        )

    _NEGATION_PREFIX_RE = re.compile(r"(?:non[-\s]|not\s+|un|in|im)$", re.IGNORECASE)

    @staticmethod
    def _is_negated(text: str, match: re.Match) -> bool:
        """Check if a regex match is preceded by a negation prefix."""
        start = match.start()
        prefix = text[max(0, start - 4) : start]
        return bool(ContentContradictionRule._NEGATION_PREFIX_RE.search(prefix))

    _CONTRADICTION_PAIRS = [
        (r"\bmove fast\b", r"\bcomprehensive tests?\b", "'move fast' vs 'comprehensive tests'"),
        (
            r"\bkeep it simple\b",
            r"\bhandle all edge cases\b",
            "'keep it simple' vs 'handle all edge cases'",
        ),
        (
            r"\bdon'?t over-?engineer\b",
            r"\bdetailed architecture\b",
            "'don't over-engineer' vs 'detailed architecture'",
        ),
        (r"\bminimal\b", r"\bexhaustive\b", "'minimal' vs 'exhaustive'"),
        (
            r"\bdon'?t add comments\b",
            r"\bdocument\s+(everything|all|every)\b",
            "'don't add comments' vs 'document everything'",
        ),
        (
            r"\bavoid abstractions?\b",
            r"\bcreate\s+(abstractions?|interfaces?|base\s+class)\b",
            "'avoid abstractions' vs 'create abstractions'",
        ),
    ]

    @property
    def rule_id(self) -> str:
        return "content-contradiction"

    @property
    def description(self) -> str:
        return "Detect likely contradictions within instruction files using keyword-pair heuristics"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        for cf in gather_all_content_blocks(context):
            body = cf.read_body()
            if not body:
                continue
            body_lower = body.lower()
            for pat_a, pat_b, desc in self._CONTRADICTION_PAIRS:
                has_a = any(
                    not self._is_negated(body_lower, m) for m in re.finditer(pat_a, body_lower)
                )
                has_b = any(
                    not self._is_negated(body_lower, m) for m in re.finditer(pat_b, body_lower)
                )
                if has_a and has_b:
                    violations.append(
                        self.violation(
                            f"Possible contradiction: {desc}",
                            block=cf,
                        )
                    )
        return violations


class ContentHookCandidateRule(Rule):
    """Detect instructions that should be automated hooks"""

    formats = None
    since = "0.7.0"

    @property
    def llm_fix_prompt(self):
        return (
            "You are fixing AI coding assistant instruction files. Replace "
            "prose instructions that describe automated workflows with a note "
            "to configure the appropriate hook instead.\n\n"
            "Rules:\n"
            "- Replace 'always run X before committing' with a comment suggesting "
            "a pre-commit hook\n"
            "- Replace 'run tests before push' with a suggestion for a pre-push hook\n"
            "- Replace 'after every change, do X' with a PostToolUse hook suggestion\n"
            "- Keep the instruction but rewrite it as a hook configuration reminder\n"
            "- Preserve markdown formatting"
        )

    _HOOK_PATTERNS = [
        (
            re.compile(r"\balways run\s+.+\s+(?:after|before)\b", re.IGNORECASE),
            "PostToolUse or PreToolUse hook",
        ),
        (
            re.compile(r"\bformat\s+(?:code|files?)\s+before\s+committ?ing\b", re.IGNORECASE),
            "pre-commit hook",
        ),
        (
            re.compile(r"\bnever\s+push\s+without\s+(?:running\s+)?tests?\b", re.IGNORECASE),
            "pre-push hook or Stop hook",
        ),
        (re.compile(r"\balways\s+lint\s+before\b", re.IGNORECASE), "pre-commit hook"),
        (
            re.compile(r"\brun\s+tests?\s+before\s+(?:every\s+)?commit\b", re.IGNORECASE),
            "pre-commit hook",
        ),
        (
            re.compile(r"\bafter\s+(?:every|each)\s+(?:change|edit|save)\b", re.IGNORECASE),
            "PostToolUse hook",
        ),
        (re.compile(r"\bbefore\s+(?:every|each)\s+commit\b", re.IGNORECASE), "pre-commit hook"),
    ]

    @property
    def rule_id(self) -> str:
        return "content-hook-candidate"

    @property
    def description(self) -> str:
        return "Detect instructions that should be automated as hooks instead of prose instructions"

    def default_severity(self) -> Severity:
        return Severity.INFO

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        for cf in gather_all_content_blocks(context):
            body = cf.read_body()
            if not body:
                continue
            for line_num, line in enumerate(body.splitlines(), 1):
                for pattern, hook_type in self._HOOK_PATTERNS:
                    if pattern.search(line):
                        violations.append(
                            self.violation(
                                f"Hook candidate: '{line.strip()[:80]}' — consider automating as a {hook_type}",
                                block=cf,
                                line=line_num,
                            )
                        )
                        break
        return violations


class ContentActionabilityScoreRule(Rule):
    """Compute an actionability score for instruction files"""

    formats = None
    since = "0.7.0"

    @property
    def llm_fix_prompt(self):
        return (
            "You are improving AI coding assistant instruction files that have "
            "low actionability scores. Make instructions more actionable by "
            "adding specific commands, file paths, and concrete actions.\n\n"
            "Rules:\n"
            "- Replace vague prose with imperative instructions\n"
            "- Add specific commands (e.g., `npm test`, `make lint`)\n"
            "- Add file paths where relevant (e.g., `src/config.ts`)\n"
            "- Convert descriptions into action items\n"
            "- Do NOT add instructions that don't match the project\n"
            "- Preserve markdown formatting"
        )

    _VERB_RE = re.compile(
        r"\b(?:use|run|create|add|remove|check|set|write|read|call|return|throw|"
        r"avoid|prefer|include|exclude|follow|implement|test|validate|verify|"
        r"handle|log|format|configure|install|update|delete|move|copy|import|"
        r"export|define|declare|initialize|override|extend|wrap|deploy|build|"
        r"commit|push|pull|merge|rebase|review|ensure|make|keep|always|never)\b",
        re.IGNORECASE,
    )
    _COMMAND_RE = re.compile(r"`[^`]+`")
    _PATH_RE = re.compile(r"(?:`[^`]*[/\\][^`]*`|[\w./\\]+\.\w{1,5})")
    WARN_THRESHOLD = 40

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
            body = cf.read_body()
            if not body:
                continue
            lines = [l for l in body.splitlines() if l.strip()]
            if len(lines) < 5:
                continue
            total = len(lines)
            verb_lines = sum(1 for l in lines if self._VERB_RE.search(l))
            cmd_lines = sum(1 for l in lines if self._COMMAND_RE.search(l))
            path_lines = sum(1 for l in lines if self._PATH_RE.search(l))

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
                    )
                )
        return violations


class ContentCognitiveChunksRule(Rule):
    """Check section organization for cognitive chunking"""

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


class ContentEmbeddedSecretsRule(Rule):
    """Detect potential secrets embedded in instruction files"""

    formats = None
    since = "0.7.0"

    @property
    def llm_fix_prompt(self):
        return (
            "You are fixing AI coding assistant instruction files that contain "
            "embedded secrets (API keys, tokens, passwords). Replace secrets "
            "with environment variable references.\n\n"
            "Rules:\n"
            "- Replace hardcoded secrets with environment variable references\n"
            "- Example: 'api_key = \"sk-abc123\"' → 'api_key = os.environ[\"API_KEY\"]'\n"
            "- For instruction prose, replace with placeholder like '$API_KEY'\n"
            "- Add a note about storing secrets in .env or environment variables\n"
            "- Do NOT remove the instruction, just redact the secret\n"
            "- Preserve markdown formatting"
        )

    _PATTERNS = [
        (re.compile(p), desc)
        for p, desc in [
            # OpenAI / Anthropic
            (r"\bsk-[a-zA-Z0-9]{20,}", "OpenAI/Anthropic API key"),
            (r"\bsk-ant-[a-zA-Z0-9\-_]{20,}", "Anthropic API key"),
            # GitHub
            (r"\bghp_[a-zA-Z0-9]{36,}", "GitHub personal access token"),
            (r"\bghs_[a-zA-Z0-9]{36,}", "GitHub server token"),
            (r"\bgho_[a-zA-Z0-9]{36,}", "GitHub OAuth token"),
            (r"\bghu_[a-zA-Z0-9]{36,}", "GitHub user token"),
            (r"\bghr_[a-zA-Z0-9]{36,}", "GitHub refresh token"),
            # GitLab
            (r"\bglpat-[a-zA-Z0-9\-_]{20,}", "GitLab personal access token"),
            # AWS
            (r"\bAKIA[0-9A-Z]{16}", "AWS access key ID"),
            (r"\bASIA[0-9A-Z]{16}", "AWS temporary access key ID"),
            # Slack
            (r"\bxoxb-[0-9]{10,}-[0-9a-zA-Z\-]+", "Slack bot token"),
            (r"\bxoxp-[0-9]{10,}-[0-9a-zA-Z\-]+", "Slack user token"),
            (r"\bxoxa-[0-9]{10,}-[0-9a-zA-Z\-]+", "Slack app token"),
            (r"\bxoxr-[0-9]{10,}-[0-9a-zA-Z\-]+", "Slack refresh token"),
            # Stripe
            (r"\bsk_live_[a-zA-Z0-9]{24,}", "Stripe secret key"),
            (r"\brk_live_[a-zA-Z0-9]{24,}", "Stripe restricted key"),
            # Google
            (r"\bAIza[0-9A-Za-z_\-]{35}", "Google API key"),
            # Twilio
            (r"\bSK[0-9a-fA-F]{32}", "Twilio API key"),
            # SendGrid
            (r"\bSG\.[a-zA-Z0-9_\-]{22}\.[a-zA-Z0-9_\-]{43}", "SendGrid API key"),
            # npm
            (r"\bnpm_[a-zA-Z0-9]{36}", "npm access token"),
            # PyPI
            (r"\bpypi-[a-zA-Z0-9]{16,}", "PyPI API token"),
            # JWT (base64.base64.base64)
            (r"\beyJ[a-zA-Z0-9_\-]*\.eyJ[a-zA-Z0-9_\-]*\.[a-zA-Z0-9_\-]+", "JSON Web Token"),
            # Private keys
            (r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----", "Private key"),
            # Generic patterns
            (r"(?i)\bpassword\s*[=:]\s*['\"][^'\"]{8,}['\"]", "Hardcoded password"),
            (r"(?i)\bapi[_-]?key\s*[=:]\s*['\"][^'\"]{16,}['\"]", "Hardcoded API key"),
            (r"(?i)\bsecret[_-]?key\s*[=:]\s*['\"][^'\"]{16,}['\"]", "Hardcoded secret key"),
            (r"(?i)\baccess[_-]?token\s*[=:]\s*['\"][^'\"]{16,}['\"]", "Hardcoded access token"),
        ]
    ]

    @property
    def rule_id(self) -> str:
        return "content-embedded-secrets"

    @property
    def description(self) -> str:
        return "Detect potential API keys, tokens, and passwords in instruction files"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        seen_paths: Set[Path] = set()
        for cf in gather_all_content_blocks(context):
            resolved = cf.path.resolve()
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            content = read_text(cf.path)
            if not content:
                continue
            for line_num, line in enumerate(content.splitlines(), 1):
                for pattern, desc in self._PATTERNS:
                    if pattern.search(line):
                        violations.append(
                            self.violation(
                                f"Potential secret detected: {desc}",
                                block=cf,
                                line=line_num,
                            )
                        )
                        break
        return violations


class ContentBannedReferencesRule(Rule):
    """Detect banned or deprecated references in instruction files"""

    formats = None
    since = "0.7.0"

    _BUILTIN_PATTERNS = [
        (r"\bgpt-3\.5\b", "gpt-3.5 is deprecated"),
        (r"\btext-davinci\b", "text-davinci models are retired"),
        (r"\bcode-davinci\b", "code-davinci models are retired"),
        (r"\bclaude-instant\b", "claude-instant is deprecated"),
        (r"\bclaude-2\b", "claude-2 is deprecated"),
        (r"\bclaude-v1\b", "claude-v1 is deprecated"),
        (r"\bclaude-3-opus\b", "claude-3-opus is deprecated"),
        (r"\bclaude-3-sonnet\b", "claude-3-sonnet is deprecated"),
        (r"\bclaude-3-haiku\b", "claude-3-haiku is deprecated"),
        (r"\bclaude-3\.5-sonnet\b", "claude-3.5-sonnet is deprecated"),
        (r"\bclaude-3\.5-haiku\b", "claude-3.5-haiku is deprecated"),
        (r"\b/v1/complete\b", "/v1/complete is deprecated — use /v1/messages"),
    ]

    config_schema = {
        "banned": {
            "type": "list",
            "default": [],
            "description": "Additional banned patterns as list of {pattern, message} dicts",
        },
        "skip-builtins": {
            "type": "bool",
            "default": False,
            "description": "Disable built-in deprecated model/API checks",
        },
    }

    @property
    def rule_id(self) -> str:
        return "content-banned-references"

    @property
    def description(self) -> str:
        return "Detect banned or deprecated model names, APIs, and custom patterns"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    @property
    def llm_fix_prompt(self):
        return (
            "You are fixing AI coding assistant instruction files that reference "
            "banned or deprecated models, APIs, or tooling.\n\n"
            "Rules:\n"
            "- Replace deprecated model names with current equivalents\n"
            "- Update retired API endpoints to current versions\n"
            "- Remove or replace banned references per the violation message\n"
            "- Preserve the intent of the instruction\n"
            "- Preserve markdown formatting"
        )

    def _get_patterns(self) -> List[Tuple[re.Pattern, str]]:
        patterns: List[Tuple[re.Pattern, str]] = []
        if not self.config.get("skip-builtins", False):
            for regex_str, msg in self._BUILTIN_PATTERNS:
                patterns.append((re.compile(regex_str, re.IGNORECASE), msg))
        for entry in self.config.get("banned", []):
            if isinstance(entry, dict) and "pattern" in entry:
                msg = entry.get("message", f"Banned reference: matches '{entry['pattern']}'")
                try:
                    patterns.append((re.compile(entry["pattern"], re.IGNORECASE), msg))
                except re.error:
                    pass
        return patterns

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        patterns = self._get_patterns()
        if not patterns:
            return []
        violations = []
        seen_paths: Set[Path] = set()
        for cf in gather_all_content_blocks(context):
            resolved = cf.path.resolve()
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            content = read_text(cf.path)
            if not content:
                continue
            for line_num, line in enumerate(content.splitlines(), 1):
                for pattern, msg in patterns:
                    if pattern.search(line):
                        violations.append(
                            self.violation(
                                f"Banned reference: {msg}",
                                block=cf,
                                line=line_num,
                            )
                        )
        return violations


class ContentInconsistentTerminologyRule(Rule):
    """Detect inconsistent terminology across instruction files"""

    formats = None
    since = "0.7.0"

    _TERM_GROUPS: List[Tuple[str, List[re.Pattern]]] = [
        (
            "directory/folder",
            [
                re.compile(r"\bdirector(?:y|ies)\b", re.IGNORECASE),
                re.compile(r"\bfolders?\b", re.IGNORECASE),
            ],
        ),
        (
            "repo/repository/codebase",
            [
                re.compile(r"\brepos?\b", re.IGNORECASE),
                re.compile(r"\brepositories\b|\brepository\b", re.IGNORECASE),
                re.compile(r"\bcodebase\b", re.IGNORECASE),
            ],
        ),
        (
            "PR/pull request/merge request",
            [
                re.compile(r"\bPRs?\b"),
                re.compile(r"\bpull\s+requests?\b", re.IGNORECASE),
                re.compile(r"\bmerge\s+requests?\b", re.IGNORECASE),
            ],
        ),
        (
            "function/method",
            [
                re.compile(r"\bfunctions?\b", re.IGNORECASE),
                re.compile(r"\bmethods?\b", re.IGNORECASE),
            ],
        ),
    ]

    MIN_FILES = 2

    @property
    def rule_id(self) -> str:
        return "content-inconsistent-terminology"

    @property
    def description(self) -> str:
        return "Detect inconsistent terminology across instruction files (e.g., mixing 'directory' and 'folder')"

    def default_severity(self) -> Severity:
        return Severity.INFO

    @property
    def llm_fix_prompt(self):
        return (
            "You are fixing AI coding assistant instruction files that use "
            "inconsistent terminology. Standardize on one term per concept "
            "across all files.\n\n"
            "Rules:\n"
            "- Pick the most common term and use it consistently\n"
            "- Prefer technical terms over informal ones (e.g., 'directory' over 'folder')\n"
            "- Update all occurrences to use the chosen term\n"
            "- Preserve markdown formatting"
        )

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        content_files = gather_all_content_blocks(context)
        if len(content_files) < self.MIN_FILES:
            return []

        violations = []
        for group_name, patterns in self._TERM_GROUPS:
            term_usage: Dict[str, int] = defaultdict(int)
            files_by_term: Dict[str, List[Path]] = defaultdict(list)
            for cf in content_files:
                body = cf.read_body()
                if not body:
                    continue
                for pattern in patterns:
                    if pattern.search(body):
                        term_usage[pattern.pattern] += 1
                        files_by_term[pattern.pattern].append(cf.path)

            used_terms = [p for p in term_usage if term_usage[p] > 0]
            if len(used_terms) >= 2:
                majority_term = max(used_terms, key=lambda p: term_usage[p])
                minority_files: Set[Path] = set()
                for term, fpaths in files_by_term.items():
                    if term != majority_term:
                        minority_files.update(fpaths)
                msg = f"Inconsistent terminology: {group_name} — multiple variants used across files. Pick one and use it consistently."
                for fpath in sorted(minority_files):
                    violations.append(self.violation(msg, file_path=fpath))

        return violations


class ContentBrokenInternalReferenceRule(Rule):
    """Detect markdown links pointing to nonexistent files"""

    formats = None
    since = "0.9.0"
    repo_types = None

    _LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
    _TEMPLATE_DIR_NAMES = {"template", "templates", "_template"}

    @property
    def rule_id(self) -> str:
        return "content-broken-internal-reference"

    @property
    def description(self) -> str:
        return "Detect markdown links where the target file does not exist"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def _is_in_template_dir(self, file_path: Path) -> bool:
        """Check if the file is inside a template directory."""
        for part in file_path.parts:
            if part in self._TEMPLATE_DIR_NAMES:
                return True
        return False

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        root = context.root_path.resolve()
        violations = []
        for cf in gather_all_content_blocks(context):
            if self._is_in_template_dir(cf.path):
                continue
            body = cf.read_body(strip_code_blocks=True)
            if not body:
                continue
            for line_num, line in enumerate(body.splitlines(), 1):
                for match in self._LINK_RE.finditer(line):
                    target = match.group(2).strip()
                    # Strip optional title text: [text](path "title")
                    if " " in target:
                        target = target.split(" ")[0]
                    # Skip URLs, anchors, and mailto
                    if target.startswith(("http://", "https://", "#", "mailto:")):
                        continue
                    # Strip anchor from path (e.g., "file.md#section")
                    target_path = target.split("#")[0]
                    if not target_path:
                        continue
                    # Resolve relative to the file containing the link
                    resolved = (cf.path.parent / target_path).resolve()
                    # Ensure the resolved path is within the repo root
                    try:
                        resolved.relative_to(root)
                    except ValueError:
                        violations.append(
                            self.violation(
                                f"Broken internal link: [{match.group(1)}]({target}) — target is outside repository",
                                block=cf,
                                line=line_num,
                            )
                        )
                        continue
                    if not resolved.exists():
                        suggestion = self._find_similar(root, cf.path.parent, target_path)
                        msg = f"Broken internal link: [{match.group(1)}]({target}) — target does not exist"
                        if suggestion:
                            msg += f" (did you mean '{suggestion}'?)"
                        violations.append(self.violation(msg, block=cf, line=line_num))
        return violations

    def _collect_repo_paths(self, root: Path) -> List[str]:
        """Collect all file paths in the repo, relative to root."""
        paths = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                d for d in dirnames if d not in {".git", "node_modules", "__pycache__", ".venv"}
            ]
            for f in filenames:
                full = Path(dirpath) / f
                try:
                    paths.append(str(full.relative_to(root)))
                except ValueError:
                    continue
        return paths

    def _find_similar(self, root: Path, link_dir: Path, target_path: str) -> Optional[str]:
        """Find a similar file path in the repo using fuzzy matching."""
        repo_paths = self._collect_repo_paths(root)
        target_name = Path(target_path).name
        candidates = [p for p in repo_paths if Path(p).name == target_name]
        if len(candidates) == 1:
            try:
                return str(Path(candidates[0]).relative_to(link_dir.relative_to(root)))
            except ValueError:
                rel = os.path.relpath(root / candidates[0], link_dir)
                return rel
        if not candidates:
            candidate_names = [Path(p).name for p in repo_paths]
            close = difflib.get_close_matches(target_name, candidate_names, n=1, cutoff=0.6)
            if close:
                candidates = [p for p in repo_paths if Path(p).name == close[0]]
        if candidates:
            try:
                rel = os.path.relpath(root / candidates[0], link_dir)
                return rel
            except ValueError:
                return candidates[0]
        return None

    def fix(
        self, context: RepositoryContext, violations: List[RuleViolation], **kwargs: object
    ) -> List[AutofixResult]:
        root = context.root_path.resolve()
        fixes_by_file: Dict[Path, List[tuple]] = defaultdict(list)
        for v in violations:
            if not v.file_path or "did you mean" not in v.message:
                continue
            suggestion = v.message.split("did you mean '")[1].rstrip("'?)")
            old_target = v.message.split("](")[1].split(")")[0]
            fixes_by_file[v.file_path].append((old_target, suggestion, v))

        results: List[AutofixResult] = []
        for fpath, replacements in fixes_by_file.items():
            try:
                content = fpath.read_text(encoding="utf-8")
            except OSError:
                continue
            fixed = content
            violations_fixed = []
            for old_target, suggestion, v in replacements:
                fixed = fixed.replace(f"]({old_target})", f"]({suggestion})")
                violations_fixed.append(v)
            if fixed != content:
                results.append(
                    AutofixResult(
                        rule_id=self.rule_id,
                        file_path=fpath,
                        confidence=AutofixConfidence.SUGGEST,
                        original_content=content,
                        fixed_content=fixed,
                        description=f"Fix {len(violations_fixed)} broken link(s) with likely matches",
                        violations_fixed=violations_fixed,
                    )
                )
        return results


class ContentUnlinkedInternalReferenceRule(Rule):
    """Detect bare path-like strings that are not wrapped in markdown link syntax"""

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
    ) -> List[AutofixResult]:
        fixes_by_file: Dict[Path, List[tuple]] = defaultdict(list)
        for v in violations:
            if not v.file_path or "autofixable" not in v.message:
                continue
            path_str = v.message.split("'")[1]
            fixes_by_file[v.file_path].append((path_str, v))

        results: List[AutofixResult] = []
        for fpath, replacements in fixes_by_file.items():
            try:
                content = fpath.read_text(encoding="utf-8")
            except OSError:
                continue
            fixed = content
            violations_fixed = []
            for path_str, v in replacements:
                pattern = rf"(?<!\[)(?<!\]\(){re.escape(path_str)}"
                fixed = re.sub(pattern, f"[{path_str}]({path_str})", fixed, count=1)
                violations_fixed.append(v)
            if fixed != content:
                results.append(
                    AutofixResult(
                        rule_id=self.rule_id,
                        file_path=fpath,
                        confidence=AutofixConfidence.SAFE,
                        original_content=content,
                        fixed_content=fixed,
                        description=f"Wrap {len(violations_fixed)} bare path(s) in markdown link syntax",
                        violations_fixed=violations_fixed,
                    )
                )
        return results


class ContentPlaceholderTextRule(Rule):
    """Detect TODO markers, bracket placeholders, and unfilled template text"""

    formats = None
    since = "0.9.0"
    repo_types = None

    _PLACEHOLDER_PATTERNS = [
        (re.compile(r"\bTODO\b"), "TODO marker"),
        (re.compile(r"\bFIXME\b"), "FIXME marker"),
        (re.compile(r"\bXXX\b"), "XXX marker"),
        (re.compile(r"\[link\s+here\]", re.IGNORECASE), "Placeholder link"),
        (re.compile(r"\[Insert\s+[^\]]+\]", re.IGNORECASE), "Insert placeholder"),
        (re.compile(r"\[If\s+[^\]]+\]", re.IGNORECASE), "Conditional placeholder"),
        (
            re.compile(
                r"\*(?:TBD|to be added|details to be added|content to be added)\*",
                re.IGNORECASE,
            ),
            "Unfilled template text",
        ),
    ]

    @property
    def rule_id(self) -> str:
        return "content-placeholder-text"

    @property
    def description(self) -> str:
        return "Detect TODO markers, bracket placeholders, and unfilled template text"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        for cf in gather_all_content_blocks(context):
            body = cf.read_body(strip_code_blocks=True)
            if not body:
                continue
            for line_num, line in enumerate(body.splitlines(), 1):
                if not line.strip():
                    continue
                for pattern, desc in self._PLACEHOLDER_PATTERNS:
                    match = pattern.search(line)
                    if match:
                        violations.append(
                            self.violation(
                                f"Placeholder text ({desc}): '{match.group()}'",
                                block=cf,
                                line=line_num,
                            )
                        )
        return violations

"""
Rules for validating GitHub Copilot instruction files
(.github/copilot-instructions.md and .instructions.md)
"""

import fnmatch
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from skillsaw.rule import AutofixConfidence, AutofixResult, Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext, HAS_COPILOT
from skillsaw.rules.builtin.content_analysis import (
    DeadReferenceScanner,
    TautologicalDetector,
    WeakLanguageDetector,
    _strip_fenced_code_blocks,
)
from skillsaw.rules.builtin.utils import read_text, parse_frontmatter, frontmatter_key_line

_VALID_FRONTMATTER_KEYS = {"applyTo", "excludeAgent"}
_VALID_EXCLUDE_AGENTS = {"code-review", "cloud-agent"}
_OVERLY_BROAD_APPLY_TO = {"*", "**", "**/*", "**/**"}
_HEADING_RE = re.compile(r"^#{1,6}\s+\S", re.MULTILINE)


def _iter_copilot_global(context: RepositoryContext):
    """Yield (path, content) for the global copilot-instructions.md if it exists."""
    path = context.root_path / ".github" / "copilot-instructions.md"
    if path.exists():
        content = read_text(path)
        if content is not None:
            yield path, content


def _iter_dot_instructions(context: RepositoryContext):
    """Yield (path, content) for all .instructions.md files in the repo."""
    for path in sorted(context.root_path.rglob(".instructions.md")):
        if path.is_dir():
            continue
        content = read_text(path)
        if content is not None:
            yield path, content
    instructions_dir = context.root_path / ".github" / "instructions"
    if instructions_dir.is_dir():
        for path in sorted(instructions_dir.rglob("*.instructions.md")):
            if path.is_dir():
                continue
            content = read_text(path)
            if content is not None:
                yield path, content


def _iter_all_copilot_files(context: RepositoryContext):
    """Yield (path, content) for all copilot instruction files."""
    seen: Set[Path] = set()
    for path, content in _iter_copilot_global(context):
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            yield path, content
    for path, content in _iter_dot_instructions(context):
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            yield path, content


def _copilot_body(content: str) -> str:
    """Return body text of a copilot instruction file (after frontmatter if present)."""
    fm, body = parse_frontmatter(content)
    return body


def _normalize_apply_to(value) -> Optional[List[str]]:
    """Normalize applyTo to a list of pattern strings."""
    if isinstance(value, str):
        return [value.strip()]
    if isinstance(value, list):
        return [str(p).strip() for p in value if isinstance(p, str)]
    return None


class CopilotInstructionsValidRule(Rule):
    """Check that .github/copilot-instructions.md is valid UTF-8 and non-empty"""

    formats = {HAS_COPILOT}

    @property
    def rule_id(self) -> str:
        return "copilot-instructions-valid"

    @property
    def description(self) -> str:
        return ".github/copilot-instructions.md must be valid UTF-8 and non-empty"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        file_path = context.root_path / ".github" / "copilot-instructions.md"
        if not file_path.exists():
            return violations

        content = read_text(file_path)
        if content is None:
            violations.append(
                self.violation(
                    "Failed to read .github/copilot-instructions.md (invalid encoding or I/O error)",
                    file_path=file_path,
                )
            )
            return violations

        if not content.strip():
            violations.append(
                self.violation(
                    ".github/copilot-instructions.md is empty",
                    file_path=file_path,
                )
            )

        return violations


def _is_valid_glob(pattern: str) -> bool:
    """Check whether a glob pattern is syntactically valid."""
    try:
        re.compile(fnmatch.translate(pattern))
        return True
    except re.error:
        return False


class CopilotDotInstructionsValidRule(Rule):
    """Check that .instructions.md files have valid YAML frontmatter with applyTo globs"""

    formats = {HAS_COPILOT}

    @property
    def rule_id(self) -> str:
        return "copilot-dot-instructions-valid"

    @property
    def description(self) -> str:
        return ".instructions.md files must have valid YAML frontmatter with applyTo glob patterns"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        for file_path in context.root_path.rglob(".instructions.md"):
            content = read_text(file_path)
            if content is None:
                violations.append(
                    self.violation(
                        f"Failed to read {file_path.name} (invalid encoding or I/O error)",
                        file_path=file_path,
                    )
                )
                continue

            if not content.strip():
                violations.append(
                    self.violation(
                        f"{file_path.name} is empty",
                        file_path=file_path,
                    )
                )
                continue

            frontmatter, _ = parse_frontmatter(content)
            if frontmatter is None:
                violations.append(
                    self.violation(
                        f"{file_path.name} is missing YAML frontmatter",
                        file_path=file_path,
                        line=1,
                    )
                )
                continue

            if "applyTo" not in frontmatter:
                violations.append(
                    self.violation(
                        f"{file_path.name} frontmatter is missing required 'applyTo' field",
                        file_path=file_path,
                        line=1,
                    )
                )
                continue

            apply_to = frontmatter["applyTo"]
            apply_to_line = frontmatter_key_line(file_path, "applyTo")

            if isinstance(apply_to, str):
                patterns = [apply_to]
            elif isinstance(apply_to, list):
                patterns = apply_to
            else:
                violations.append(
                    self.violation(
                        f"{file_path.name} 'applyTo' must be a string or list of strings",
                        file_path=file_path,
                        line=apply_to_line,
                    )
                )
                continue

            for pattern in patterns:
                if not isinstance(pattern, str):
                    violations.append(
                        self.violation(
                            f"{file_path.name} 'applyTo' contains non-string value: {pattern!r}",
                            file_path=file_path,
                            line=apply_to_line,
                        )
                    )
                elif not pattern.strip():
                    violations.append(
                        self.violation(
                            f"{file_path.name} 'applyTo' contains empty pattern",
                            file_path=file_path,
                            line=apply_to_line,
                        )
                    )
                elif not _is_valid_glob(pattern):
                    violations.append(
                        self.violation(
                            f"{file_path.name} 'applyTo' contains invalid glob pattern: {pattern!r}",
                            file_path=file_path,
                            line=apply_to_line,
                        )
                    )

        return violations


# ---------------------------------------------------------------------------
# 10 deep Copilot instruction rules (auto-enabled when HAS_COPILOT detected)
# ---------------------------------------------------------------------------


class CopilotInstructionsLengthRule(Rule):
    """Warn when copilot instruction files exceed a line threshold"""

    formats = {HAS_COPILOT}
    config_schema = {
        "max-lines": {
            "type": "integer",
            "default": 200,
            "description": "Maximum lines before warning (copilot context budget)",
        }
    }

    @property
    def rule_id(self) -> str:
        return "copilot-instructions-length"

    @property
    def description(self) -> str:
        return "Copilot instruction files that are too long waste context budget"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        max_lines = self.config.get("max-lines", 200)
        for path, content in _iter_all_copilot_files(context):
            line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
            if line_count > max_lines:
                violations.append(
                    self.violation(
                        f"Instruction file is {line_count} lines (max {max_lines}). "
                        f"Long instructions dilute Copilot's attention — "
                        f"keep instructions concise and focused",
                        file_path=path,
                    )
                )
        return violations


class CopilotInstructionsLanguageQualityRule(Rule):
    """Detect weak/hedging language in copilot instruction files"""

    formats = {HAS_COPILOT}

    @property
    def rule_id(self) -> str:
        return "copilot-instructions-language-quality"

    @property
    def description(self) -> str:
        return "Weak/hedging language wastes instruction budget (try to, if possible, etc.)"

    def default_severity(self) -> Severity:
        return Severity.INFO

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        detector = WeakLanguageDetector()
        for path, _ in _iter_all_copilot_files(context):
            matches = detector.analyze(path)
            for match in matches:
                violations.append(
                    self.violation(
                        f"Weak language: '{match.phrase}' ({match.category}). "
                        f"{match.suggested_fix}",
                        file_path=path,
                        line=match.line,
                    )
                )
        return violations

    def fix(
        self,
        context: RepositoryContext,
        violations: List[RuleViolation],
    ) -> List[AutofixResult]:
        results: List[AutofixResult] = []
        files: Dict[Path, List[RuleViolation]] = {}
        for v in violations:
            if v.file_path:
                files.setdefault(v.file_path, []).append(v)

        detector = WeakLanguageDetector()
        for path, file_violations in files.items():
            content = read_text(path)
            if content is None:
                continue
            matches = detector.analyze(path)
            if not matches:
                continue
            body = _copilot_body(content)
            fixed_body = _strip_fenced_code_blocks(body)
            lines = body.split("\n")
            changed = False
            for match in matches:
                if match.line <= len(lines):
                    line = lines[match.line - 1]
                    replacement = re.sub(
                        re.escape(match.phrase),
                        "",
                        line,
                        count=1,
                        flags=re.IGNORECASE,
                    )
                    replacement = re.sub(r"  +", " ", replacement).strip()
                    if replacement != line.strip():
                        lines[match.line - 1] = replacement
                        changed = True
            if changed:
                fm, _ = parse_frontmatter(content)
                if fm is not None:
                    fm_match = re.match(r"^---[ \t]*\n.*?\n---[ \t]*\n?", content, re.DOTALL)
                    prefix = fm_match.group(0) if fm_match else ""
                    fixed_content = prefix + "\n".join(lines)
                else:
                    fixed_content = "\n".join(lines)
                results.append(
                    AutofixResult(
                        rule_id=self.rule_id,
                        file_path=path,
                        confidence=AutofixConfidence.SUGGEST,
                        original_content=content,
                        fixed_content=fixed_content,
                        description=f"Remove weak/hedging language from {path.name}",
                        violations_fixed=file_violations,
                    )
                )
        return results


class CopilotInstructionsActionabilityRule(Rule):
    """Detect tautological/non-actionable instructions in copilot files"""

    formats = {HAS_COPILOT}

    @property
    def rule_id(self) -> str:
        return "copilot-instructions-actionability"

    @property
    def description(self) -> str:
        return "Tautological instructions that models already follow waste context budget"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        detector = TautologicalDetector()
        for path, _ in _iter_all_copilot_files(context):
            matches = detector.analyze(path)
            for match in matches:
                violations.append(
                    self.violation(
                        f"Tautological instruction: '{match.phrase}'. " f"{match.reason}",
                        file_path=path,
                        line=match.line,
                    )
                )
        return violations

    def fix(
        self,
        context: RepositoryContext,
        violations: List[RuleViolation],
    ) -> List[AutofixResult]:
        results: List[AutofixResult] = []
        files: Dict[Path, List[RuleViolation]] = {}
        for v in violations:
            if v.file_path:
                files.setdefault(v.file_path, []).append(v)

        detector = TautologicalDetector()
        for path, file_violations in files.items():
            content = read_text(path)
            if content is None:
                continue
            matches = detector.analyze(path)
            if not matches:
                continue
            lines_to_remove: Set[int] = set()
            for match in matches:
                lines_to_remove.add(match.line)
            lines = content.split("\n")
            fixed_lines = [line for i, line in enumerate(lines, 1) if i not in lines_to_remove]
            fixed_content = "\n".join(fixed_lines)
            if fixed_content != content:
                results.append(
                    AutofixResult(
                        rule_id=self.rule_id,
                        file_path=path,
                        confidence=AutofixConfidence.SAFE,
                        original_content=content,
                        fixed_content=fixed_content,
                        description=f"Remove tautological instructions from {path.name}",
                        violations_fixed=file_violations,
                    )
                )
        return results


class CopilotInstructionsStaleRefsRule(Rule):
    """Detect dead file/path references in copilot instruction files"""

    formats = {HAS_COPILOT}

    @property
    def rule_id(self) -> str:
        return "copilot-instructions-stale-refs"

    @property
    def description(self) -> str:
        return "References to non-existent files, npm scripts, or make targets"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        scanner = DeadReferenceScanner()
        for path, _ in _iter_all_copilot_files(context):
            refs = scanner.analyze(path, context.root_path)
            for ref in refs:
                violations.append(
                    self.violation(
                        f"Reference to '{ref.reference}' appears broken "
                        f"(expected at {ref.expected_path})",
                        file_path=path,
                        line=ref.line,
                    )
                )
        return violations


class CopilotInstructionsDuplicationRule(Rule):
    """Detect duplicate content across copilot instruction files"""

    formats = {HAS_COPILOT}
    config_schema = {
        "similarity-threshold": {
            "type": "float",
            "default": 0.8,
            "description": "Minimum similarity ratio (0-1) to flag as duplicate",
        }
    }

    @property
    def rule_id(self) -> str:
        return "copilot-instructions-duplication"

    @property
    def description(self) -> str:
        return "Duplicate content across instruction files wastes Copilot context budget"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        threshold = self.config.get("similarity-threshold", 0.8)

        bodies: List[Tuple[Path, str]] = []
        for path, content in _iter_all_copilot_files(context):
            body = _copilot_body(content).strip()
            if body and len(body) > 50:
                bodies.append((path, body))

        reported: Set[Tuple[str, str]] = set()
        for i, (path_a, body_a) in enumerate(bodies):
            for path_b, body_b in bodies[i + 1 :]:
                ratio = SequenceMatcher(None, body_a, body_b).ratio()
                if ratio >= threshold:
                    pair = tuple(sorted([str(path_a), str(path_b)]))
                    if pair in reported:
                        continue
                    reported.add(pair)
                    pct = int(ratio * 100)
                    violations.append(
                        self.violation(
                            f"Content is {pct}% similar to "
                            f"{path_b.relative_to(context.root_path)}. "
                            f"Duplicate instructions waste Copilot's context budget",
                            file_path=path_a,
                        )
                    )
        return violations


class CopilotInstructionsScopeRule(Rule):
    """Validate applyTo glob scope in .instructions.md files"""

    formats = {HAS_COPILOT}

    @property
    def rule_id(self) -> str:
        return "copilot-instructions-scope"

    @property
    def description(self) -> str:
        return "applyTo patterns should not be overly broad — narrow scope improves relevance"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        for path, content in _iter_dot_instructions(context):
            fm, _ = parse_frontmatter(content)
            if fm is None or "applyTo" not in fm:
                continue
            patterns = _normalize_apply_to(fm["applyTo"])
            if patterns is None:
                continue
            line = frontmatter_key_line(path, "applyTo")
            for pattern in patterns:
                if pattern in _OVERLY_BROAD_APPLY_TO:
                    violations.append(
                        self.violation(
                            f"applyTo pattern '{pattern}' matches all files. "
                            f"Use a specific pattern like '**/*.py' to target "
                            f"relevant files and reduce context noise",
                            file_path=path,
                            line=line,
                        )
                    )
                if not pattern.strip():
                    continue
                matched = list(context.root_path.glob(pattern))
                if not matched:
                    violations.append(
                        self.violation(
                            f"applyTo pattern '{pattern}' matches no files in "
                            f"the workspace — these instructions will never apply",
                            file_path=path,
                            line=line,
                        )
                    )
        return violations

    def fix(
        self,
        context: RepositoryContext,
        violations: List[RuleViolation],
    ) -> List[AutofixResult]:
        results: List[AutofixResult] = []
        for v in violations:
            if not v.file_path or "matches all files" not in v.message:
                continue
            content = read_text(v.file_path)
            if content is None:
                continue
            fm, _ = parse_frontmatter(content)
            if fm is None or "applyTo" not in fm:
                continue
            patterns = _normalize_apply_to(fm["applyTo"])
            if not patterns:
                continue
            parent = v.file_path.parent
            extensions: Set[str] = set()
            for child in parent.rglob("*"):
                if child.is_file() and child.suffix and child.name != ".instructions.md":
                    extensions.add(child.suffix)
            if not extensions:
                continue
            ext_pattern = ",".join(sorted(ext.lstrip(".") for ext in extensions))
            suggested = (
                f"**/*.{{{ext_pattern}}}" if len(extensions) > 1 else f"**/*{sorted(extensions)[0]}"
            )
            fixed_content = re.sub(
                r"(applyTo\s*:\s*)[^\n]+",
                f'\\1"{suggested}"',
                content,
                count=1,
            )
            if fixed_content != content:
                results.append(
                    AutofixResult(
                        rule_id=self.rule_id,
                        file_path=v.file_path,
                        confidence=AutofixConfidence.SUGGEST,
                        original_content=content,
                        fixed_content=fixed_content,
                        description=(
                            f"Narrow applyTo from broad glob to '{suggested}' "
                            f"in {v.file_path.name}"
                        ),
                        violations_fixed=[v],
                    )
                )
        return results


class CopilotInstructionsFormatRule(Rule):
    """Validate markdown structure of copilot instruction files"""

    formats = {HAS_COPILOT}
    config_schema = {
        "min-lines-for-headings": {
            "type": "integer",
            "default": 20,
            "description": "Minimum lines before requiring markdown headings",
        }
    }

    @property
    def rule_id(self) -> str:
        return "copilot-instructions-format"

    @property
    def description(self) -> str:
        return "Instruction files should use markdown headings for structure"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        min_lines = self.config.get("min-lines-for-headings", 20)

        for path, content in _iter_all_copilot_files(context):
            body = _copilot_body(content)

            if not body.strip():
                fm, _ = parse_frontmatter(content)
                if fm is not None:
                    violations.append(
                        self.violation(
                            "Instruction file has frontmatter but no content body. "
                            "Add instructions for the file to be useful",
                            file_path=path,
                        )
                    )
                continue

            line_count = body.count("\n") + 1
            if line_count >= min_lines and not _HEADING_RE.search(body):
                violations.append(
                    self.violation(
                        f"Instruction file is {line_count} lines with no markdown "
                        f"headings. Use headings (## Section) to organize instructions "
                        f"for better Copilot comprehension",
                        file_path=path,
                    )
                )
        return violations

    def fix(
        self,
        context: RepositoryContext,
        violations: List[RuleViolation],
    ) -> List[AutofixResult]:
        results: List[AutofixResult] = []
        for v in violations:
            if not v.file_path:
                continue
            content = read_text(v.file_path)
            if content is None:
                continue

            if "no content body" in v.message:
                stem = v.file_path.stem.replace(".instructions", "")
                if not stem:
                    stem = "Instructions"
                template = f"\n# {stem.replace('-', ' ').title()}\n\nTODO: Add instructions here.\n"
                fixed = content.rstrip() + "\n" + template
                results.append(
                    AutofixResult(
                        rule_id=self.rule_id,
                        file_path=v.file_path,
                        confidence=AutofixConfidence.SUGGEST,
                        original_content=content,
                        fixed_content=fixed,
                        description=f"Add template body to {v.file_path.name}",
                        violations_fixed=[v],
                    )
                )

            elif "no markdown headings" in v.message:
                fm, body = parse_frontmatter(content)
                if fm is not None:
                    fm_match = re.match(r"^---[ \t]*\n.*?\n---[ \t]*\n?", content, re.DOTALL)
                    prefix = fm_match.group(0) if fm_match else ""
                    fixed = prefix + "# Instructions\n\n" + body
                else:
                    fixed = "# Instructions\n\n" + content
                results.append(
                    AutofixResult(
                        rule_id=self.rule_id,
                        file_path=v.file_path,
                        confidence=AutofixConfidence.SUGGEST,
                        original_content=content,
                        fixed_content=fixed,
                        description=f"Add heading structure to {v.file_path.name}",
                        violations_fixed=[v],
                    )
                )
        return results


class CopilotInstructionsConflictRule(Rule):
    """Detect contradictions between global and local instruction files"""

    formats = {HAS_COPILOT}

    _POLARITY_PATTERNS = [
        (
            re.compile(r"\balways\s+use\s+(\w+)", re.IGNORECASE),
            re.compile(r"\b(?:never|don'?t|do\s+not)\s+use\s+(\w+)", re.IGNORECASE),
            "use",
        ),
        (
            re.compile(r"\balways\s+add\s+(\w+)", re.IGNORECASE),
            re.compile(r"\b(?:never|don'?t|do\s+not)\s+add\s+(\w+)", re.IGNORECASE),
            "add",
        ),
        (
            re.compile(r"\balways\s+write\s+(\w+)", re.IGNORECASE),
            re.compile(r"\b(?:never|don'?t|do\s+not)\s+write\s+(\w+)", re.IGNORECASE),
            "write",
        ),
        (
            re.compile(r"\balways\s+include\s+(\w+)", re.IGNORECASE),
            re.compile(r"\b(?:never|don'?t|do\s+not)\s+include\s+(\w+)", re.IGNORECASE),
            "include",
        ),
    ]

    @property
    def rule_id(self) -> str:
        return "copilot-instructions-conflict"

    @property
    def description(self) -> str:
        return "Contradictions between instruction files cause non-deterministic behavior"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        file_directives: Dict[Path, List[Tuple[int, str, str, str]]] = {}

        for path, content in _iter_all_copilot_files(context):
            body = _copilot_body(content)
            stripped = _strip_fenced_code_blocks(body)
            directives: List[Tuple[int, str, str, str]] = []
            for line_num, line in enumerate(stripped.splitlines(), 1):
                for pos_re, neg_re, verb in self._POLARITY_PATTERNS:
                    for m in pos_re.finditer(line):
                        directives.append((line_num, "positive", verb, m.group(1).lower()))
                    for m in neg_re.finditer(line):
                        directives.append((line_num, "negative", verb, m.group(1).lower()))
            if directives:
                file_directives[path] = directives

        paths = list(file_directives.keys())
        for i, path_a in enumerate(paths):
            for path_b in paths[i + 1 :]:
                for line_a, pol_a, verb_a, obj_a in file_directives[path_a]:
                    for line_b, pol_b, verb_b, obj_b in file_directives[path_b]:
                        if verb_a == verb_b and obj_a == obj_b and pol_a != pol_b:
                            violations.append(
                                self.violation(
                                    f"Conflicting instructions: "
                                    f"'{verb_a} {obj_a}' is "
                                    f"{'required' if pol_a == 'positive' else 'prohibited'} "
                                    f"here but "
                                    f"{'prohibited' if pol_a == 'positive' else 'required'} "
                                    f"in {path_b.relative_to(context.root_path)}:{line_b}. "
                                    f"Copilot's choice between conflicting instructions "
                                    f"is non-deterministic",
                                    file_path=path_a,
                                    line=line_a,
                                )
                            )
        return violations


class CopilotInstructionsFrontmatterKeysRule(Rule):
    """Validate frontmatter keys in .instructions.md files"""

    formats = {HAS_COPILOT}

    @property
    def rule_id(self) -> str:
        return "copilot-instructions-frontmatter-keys"

    @property
    def description(self) -> str:
        return "Only applyTo and excludeAgent are valid frontmatter keys in .instructions.md"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        for path, content in _iter_dot_instructions(context):
            fm, _ = parse_frontmatter(content)
            if fm is None:
                continue
            unknown = set(fm.keys()) - _VALID_FRONTMATTER_KEYS
            for key in sorted(unknown):
                violations.append(
                    self.violation(
                        f"Unknown frontmatter key '{key}' (ignored by Copilot). "
                        f"Valid keys: applyTo, excludeAgent",
                        file_path=path,
                        line=frontmatter_key_line(path, key),
                    )
                )
        return violations

    def fix(
        self,
        context: RepositoryContext,
        violations: List[RuleViolation],
    ) -> List[AutofixResult]:
        results: List[AutofixResult] = []
        files: Dict[Path, List[RuleViolation]] = {}
        for v in violations:
            if v.file_path:
                files.setdefault(v.file_path, []).append(v)

        fm_re = re.compile(r"^---[ \t]*\n(.*?)---[ \t]*\n?", re.DOTALL)
        for path, file_violations in files.items():
            content = read_text(path)
            if content is None:
                continue
            m = fm_re.match(content)
            if not m:
                continue
            fm, _ = parse_frontmatter(content)
            if fm is None:
                continue
            unknown_keys = set(fm.keys()) - _VALID_FRONTMATTER_KEYS
            if not unknown_keys:
                continue
            fm_text = m.group(1)
            fixed_fm = fm_text
            for key in unknown_keys:
                fixed_fm = re.sub(
                    rf"^{re.escape(key)}\s*:.*\n?",
                    "",
                    fixed_fm,
                    flags=re.MULTILINE,
                )
            if fixed_fm != fm_text:
                suffix = "\n" if fixed_fm and not fixed_fm.endswith("\n") else ""
                fixed_content = "---\n" + fixed_fm + suffix + content[m.end() :]
                results.append(
                    AutofixResult(
                        rule_id=self.rule_id,
                        file_path=path,
                        confidence=AutofixConfidence.SAFE,
                        original_content=content,
                        fixed_content=fixed_content,
                        description=f"Remove unknown frontmatter keys from {path.name}",
                        violations_fixed=file_violations,
                    )
                )
        return results


class CopilotInstructionsExcludeAgentRule(Rule):
    """Validate excludeAgent values in .instructions.md frontmatter"""

    formats = {HAS_COPILOT}

    @property
    def rule_id(self) -> str:
        return "copilot-instructions-exclude-agent"

    @property
    def description(self) -> str:
        return "excludeAgent must be 'code-review' or 'cloud-agent'"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        for path, content in _iter_dot_instructions(context):
            fm, _ = parse_frontmatter(content)
            if fm is None or "excludeAgent" not in fm:
                continue
            value = fm["excludeAgent"]
            line = frontmatter_key_line(path, "excludeAgent")

            if isinstance(value, str):
                values = [value]
            elif isinstance(value, list):
                values = value
            else:
                violations.append(
                    self.violation(
                        f"excludeAgent must be a string or list of strings, "
                        f"got {type(value).__name__}",
                        file_path=path,
                        line=line,
                    )
                )
                continue

            for val in values:
                if not isinstance(val, str):
                    violations.append(
                        self.violation(
                            f"excludeAgent list items must be strings, "
                            f"got {type(val).__name__}: {val!r}",
                            file_path=path,
                            line=line,
                        )
                    )
                elif val not in _VALID_EXCLUDE_AGENTS:
                    violations.append(
                        self.violation(
                            f"Invalid excludeAgent value '{val}'. "
                            f"Valid values: code-review, cloud-agent",
                            file_path=path,
                            line=line,
                        )
                    )
        return violations

    def fix(
        self,
        context: RepositoryContext,
        violations: List[RuleViolation],
    ) -> List[AutofixResult]:
        results: List[AutofixResult] = []
        _CORRECTIONS = {
            "codereview": "code-review",
            "code_review": "code-review",
            "review": "code-review",
            "code review": "code-review",
            "cloudagent": "cloud-agent",
            "cloud_agent": "cloud-agent",
            "agent": "cloud-agent",
            "cloud agent": "cloud-agent",
        }
        for v in violations:
            if not v.file_path or "Invalid excludeAgent value" not in v.message:
                continue
            content = read_text(v.file_path)
            if content is None:
                continue
            match = re.search(r"'([^']+)'", v.message)
            if not match:
                continue
            bad_val = match.group(1)
            corrected = _CORRECTIONS.get(bad_val.lower())
            if corrected is None:
                continue
            fixed_content = content.replace(bad_val, corrected, 1)
            if fixed_content != content:
                results.append(
                    AutofixResult(
                        rule_id=self.rule_id,
                        file_path=v.file_path,
                        confidence=AutofixConfidence.SAFE,
                        original_content=content,
                        fixed_content=fixed_content,
                        description=(f"Fix excludeAgent value '{bad_val}' → '{corrected}'"),
                        violations_fixed=[v],
                    )
                )
        return results

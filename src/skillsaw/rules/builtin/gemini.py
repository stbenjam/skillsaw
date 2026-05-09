"""
Rules for validating GEMINI.md instruction files.

Covers import validation, circular/depth checks, scoped-package false
positives, hierarchy consistency, size limits, dead file refs, and
content-quality checks (weak language, tautological instructions,
critical position).
"""

import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from skillsaw.context import RepositoryContext
from skillsaw.rule import AutofixConfidence, AutofixResult, Rule, RuleViolation, Severity
from skillsaw.rules.builtin.utils import read_text

_IMPORT_RE = re.compile(r"^\s*@(\S+)")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)", re.MULTILINE)

_SIZE_WARN = 150
_SIZE_ERROR = 500
_MAX_IMPORT_DEPTH = 5

_WEAK_PHRASES = [
    "try to",
    "maybe",
    "if possible",
    "you could",
    "you might",
    "consider",
    "perhaps",
    "it would be nice",
    "ideally",
    "when you get a chance",
    "at some point",
    "feel free to",
]
_WEAK_RE = re.compile(
    r"\b(" + "|".join(re.escape(p) for p in _WEAK_PHRASES) + r")\b",
    re.IGNORECASE,
)

_TAUTOLOGICAL_PATTERNS = [
    (re.compile(r"\byou are an? ai\b", re.IGNORECASE), "you are an AI"),
    (
        re.compile(
            r"\byou are a (?:helpful |large )?(?:language )?(?:model|assistant)\b", re.IGNORECASE
        ),
        "you are a model/assistant",
    ),
    (
        re.compile(r"\brespond in (?:english|the same language)\b", re.IGNORECASE),
        "respond in English",
    ),
    (
        re.compile(r"\bfollow the (?:instructions|rules) (?:below|above)\b", re.IGNORECASE),
        "follow the instructions",
    ),
    (
        re.compile(r"\bdo what (?:the user|I) (?:asks?|says?|tells?)\b", re.IGNORECASE),
        "do what the user asks",
    ),
    (re.compile(r"\bbe helpful\b", re.IGNORECASE), "be helpful"),
]

_FILE_REF_RE = re.compile(
    r"(?<![`@\w])" r"((?:\.{1,2}/)?(?:[\w.+-]+/)+[\w.+-]+\.[\w]+)" r"(?![`\w])"
)


def _find_gemini_files(root: Path) -> List[Path]:
    results = []
    root_resolved = root.resolve()
    root_file = root / "GEMINI.md"
    if root_file.exists():
        results.append(root_file)
    try:
        for child in sorted(root.rglob("GEMINI.md")):
            if child == root_file:
                continue
            rel = child.relative_to(root_resolved)
            if any(part.startswith(".") for part in rel.parts[:-1]):
                continue
            results.append(child)
    except OSError:
        pass
    return results


def _extract_imports(content: str) -> List[Tuple[int, str]]:
    imports = []
    for line_num, line in enumerate(content.splitlines(), 1):
        m = _IMPORT_RE.match(line)
        if m:
            imports.append((line_num, m.group(1)))
    return imports


def _is_scoped_package(ref: str) -> bool:
    """Check if ref (already stripped of leading @) looks like an npm scope: org/pkg-name.

    The import regex strips the leading @, so @angular/core → "angular/core".
    Scoped packages have no file extension and match org/pkg-name.
    """
    if "/" not in ref:
        return False
    parts = ref.split("/")
    if len(parts) != 2:
        return False
    org, pkg = parts
    if not re.match(r"^[\w-]+$", org) or not re.match(r"^[\w.-]+$", pkg):
        return False
    if "." in pkg:
        return False
    return True


# ---------------------------------------------------------------------------
# Rule 1: gemini-import-valid
# ---------------------------------------------------------------------------


class GeminiImportValidRule(Rule):
    @property
    def rule_id(self) -> str:
        return "gemini-import-valid"

    @property
    def description(self) -> str:
        return "Validate that @import targets in GEMINI.md resolve to existing files"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        for file_path in _find_gemini_files(context.root_path):
            content = read_text(file_path)
            if content is None:
                continue
            base_dir = file_path.parent
            for line_num, ref in _extract_imports(content):
                if _is_scoped_package(ref):
                    continue
                target = (base_dir / ref).resolve()
                try:
                    target.relative_to(context.root_path.resolve())
                except ValueError:
                    violations.append(
                        self.violation(
                            f"Import '@{ref}' escapes repository root",
                            file_path=file_path,
                            line=line_num,
                        )
                    )
                    continue
                if not target.exists():
                    violations.append(
                        self.violation(
                            f"Import '@{ref}' references non-existent path",
                            file_path=file_path,
                            line=line_num,
                        )
                    )
        return violations


# ---------------------------------------------------------------------------
# Rule 2: gemini-import-circular
# ---------------------------------------------------------------------------


class GeminiImportCircularRule(Rule):
    @property
    def rule_id(self) -> str:
        return "gemini-import-circular"

    @property
    def description(self) -> str:
        return "Detect circular @import references in GEMINI.md files"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        graph: Dict[Path, List[Tuple[int, Path]]] = {}

        def _build_graph(file_path: Path):
            resolved = file_path.resolve()
            if resolved in graph:
                return
            content = read_text(file_path)
            if content is None:
                graph[resolved] = []
                return
            edges: List[Tuple[int, Path]] = []
            base_dir = file_path.parent
            for line_num, ref in _extract_imports(content):
                if _is_scoped_package(ref):
                    continue
                target = (base_dir / ref).resolve()
                if target.exists() and target.is_file():
                    edges.append((line_num, target))
            graph[resolved] = edges
            for _, target in edges:
                _build_graph(target)

        for file_path in _find_gemini_files(context.root_path):
            _build_graph(file_path)

        reported: Set[frozenset] = set()
        for start in graph:
            self._dfs(start, [], set(), graph, context, violations, reported)
        return violations

    def _dfs(
        self,
        node: Path,
        path: List[Tuple[Path, int]],
        visiting: Set[Path],
        graph: Dict[Path, List[Tuple[int, Path]]],
        context: RepositoryContext,
        violations: List[RuleViolation],
        reported: Set[frozenset],
    ):
        if node in visiting:
            cycle_nodes = [n for n, _ in path]
            idx = cycle_nodes.index(node)
            cycle_path = path[idx:]
            cycle_key = frozenset(n for n, _ in cycle_path)
            if cycle_key in reported:
                return
            reported.add(cycle_key)
            chain = " -> ".join(
                str(n.relative_to(context.root_path.resolve())) for n, _ in cycle_path
            )
            chain += f" -> {node.relative_to(context.root_path.resolve())}"
            first_file, first_line = cycle_path[0]
            violations.append(
                self.violation(
                    f"Circular import detected: {chain}",
                    file_path=first_file,
                    line=first_line,
                )
            )
            return
        if node not in graph:
            return
        visiting.add(node)
        for line_num, target in graph[node]:
            self._dfs(
                target, path + [(node, line_num)], visiting, graph, context, violations, reported
            )
        visiting.remove(node)


# ---------------------------------------------------------------------------
# Rule 3: gemini-import-depth
# ---------------------------------------------------------------------------


class GeminiImportDepthRule(Rule):
    @property
    def rule_id(self) -> str:
        return "gemini-import-depth"

    @property
    def description(self) -> str:
        return "Warn when GEMINI.md import chains exceed depth 5"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        for file_path in _find_gemini_files(context.root_path):
            content = read_text(file_path)
            if content is None:
                continue
            base_dir = file_path.parent
            for line_num, ref in _extract_imports(content):
                if _is_scoped_package(ref):
                    continue
                target = (base_dir / ref).resolve()
                if not target.exists():
                    continue
                depth = self._measure_depth(target, set(), context.root_path)
                if depth > _MAX_IMPORT_DEPTH:
                    chain = self._build_chain(target, set(), context.root_path, [])
                    chain_str = " -> ".join(chain[: _MAX_IMPORT_DEPTH + 2])
                    violations.append(
                        self.violation(
                            f"Import depth exceeds {_MAX_IMPORT_DEPTH}: {chain_str}",
                            file_path=file_path,
                            line=line_num,
                        )
                    )
        return violations

    def _measure_depth(self, path: Path, seen: Set[Path], root: Path) -> int:
        if path in seen:
            return 0
        seen.add(path)
        content = read_text(path)
        if content is None:
            return 0
        max_child = 0
        base_dir = path.parent
        for _, ref in _extract_imports(content):
            if _is_scoped_package(ref):
                continue
            target = (base_dir / ref).resolve()
            if target.exists():
                child_depth = self._measure_depth(target, seen, root)
                max_child = max(max_child, child_depth)
        seen.discard(path)
        return 1 + max_child

    def _build_chain(self, path: Path, seen: Set[Path], root: Path, chain: List[str]) -> List[str]:
        try:
            rel = str(path.relative_to(root.resolve()))
        except ValueError:
            rel = str(path)
        chain.append(rel)
        if path in seen or len(chain) > _MAX_IMPORT_DEPTH + 2:
            return chain
        seen.add(path)
        content = read_text(path)
        if content is None:
            return chain
        base_dir = path.parent
        for _, ref in _extract_imports(content):
            if _is_scoped_package(ref):
                continue
            target = (base_dir / ref).resolve()
            if target.exists():
                self._build_chain(target, seen, root, chain)
                break
        return chain


# ---------------------------------------------------------------------------
# Rule 4: gemini-scope-false-positive
# ---------------------------------------------------------------------------


class GeminiScopeFalsePositiveRule(Rule):
    @property
    def rule_id(self) -> str:
        return "gemini-scope-false-positive"

    @property
    def description(self) -> str:
        return "Detect @scope/package-name patterns that look like npm scoped packages, not imports"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        for file_path in _find_gemini_files(context.root_path):
            content = read_text(file_path)
            if content is None:
                continue
            base_dir = file_path.parent
            for line_num, ref in _extract_imports(content):
                if not _is_scoped_package(ref):
                    continue
                target = (base_dir / ref).resolve()
                if target.exists():
                    continue
                violations.append(
                    self.violation(
                        f"'@{ref}' looks like an npm scoped package, not an import — "
                        f"wrap in backticks to prevent parsing",
                        file_path=file_path,
                        line=line_num,
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

        for fpath, file_violations in files.items():
            content = read_text(fpath)
            if content is None:
                continue
            lines = content.splitlines(True)
            fixed_lines = list(lines)
            for v in file_violations:
                if v.line and 1 <= v.line <= len(lines):
                    idx = v.line - 1
                    line = lines[idx]
                    m = _IMPORT_RE.match(line)
                    if m:
                        ref = m.group(1)
                        fixed_lines[idx] = line.replace(f"@{ref}", f"`@{ref}`", 1)
            fixed = "".join(fixed_lines)
            if fixed != content:
                results.append(
                    AutofixResult(
                        rule_id=self.rule_id,
                        file_path=fpath,
                        confidence=AutofixConfidence.SAFE,
                        original_content=content,
                        fixed_content=fixed,
                        description="Wrapped scoped package references in backticks",
                        violations_fixed=file_violations,
                    )
                )
        return results


# ---------------------------------------------------------------------------
# Rule 5: gemini-hierarchy-consistency
# ---------------------------------------------------------------------------


class GeminiHierarchyConsistencyRule(Rule):
    @property
    def rule_id(self) -> str:
        return "gemini-hierarchy-consistency"

    @property
    def description(self) -> str:
        return "Check subdirectory GEMINI.md files for contradictions with parent"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        files = _find_gemini_files(context.root_path)
        if len(files) < 2:
            return violations

        parent_headings: Dict[Path, Set[str]] = {}
        for file_path in files:
            content = read_text(file_path)
            if content is None:
                continue
            headings = set()
            for match in _HEADING_RE.finditer(content):
                headings.add(match.group(2).strip().lower())
            parent_headings[file_path] = headings

        for file_path in files:
            parent_dir = file_path.parent
            parent_file = self._find_parent_gemini(parent_dir, context.root_path)
            if parent_file is None or parent_file not in parent_headings:
                continue
            child_headings = parent_headings.get(file_path, set())
            if not child_headings:
                continue
            overlap = child_headings & parent_headings[parent_file]
            if overlap:
                examples = ", ".join(sorted(list(overlap)[:3]))
                violations.append(
                    self.violation(
                        f"GEMINI.md redefines headings from parent: {examples}",
                        file_path=file_path,
                    )
                )
        return violations

    def _find_parent_gemini(self, child_dir: Path, root: Path) -> Optional[Path]:
        current = child_dir.parent
        root_resolved = root.resolve()
        while current.resolve() >= root_resolved:
            candidate = current / "GEMINI.md"
            if candidate.exists():
                return candidate
            if current.resolve() == root_resolved:
                break
            current = current.parent
        return None


# ---------------------------------------------------------------------------
# Rule 6: gemini-size-limit
# ---------------------------------------------------------------------------


class GeminiSizeLimitRule(Rule):
    config_schema = {
        "warn_lines": {
            "type": "integer",
            "default": _SIZE_WARN,
            "description": "Line count warning threshold",
        },
        "error_lines": {
            "type": "integer",
            "default": _SIZE_ERROR,
            "description": "Line count error threshold",
        },
    }

    @property
    def rule_id(self) -> str:
        return "gemini-size-limit"

    @property
    def description(self) -> str:
        return "Warn when GEMINI.md is too large"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        warn = self.config.get("warn_lines", _SIZE_WARN)
        error = self.config.get("error_lines", _SIZE_ERROR)

        for file_path in _find_gemini_files(context.root_path):
            content = read_text(file_path)
            if content is None:
                continue
            line_count = len(content.splitlines())
            if line_count >= error:
                violations.append(
                    self.violation(
                        f"GEMINI.md is {line_count} lines (exceeds {error} line limit)",
                        file_path=file_path,
                        severity=Severity.ERROR,
                    )
                )
            elif line_count >= warn:
                violations.append(
                    self.violation(
                        f"GEMINI.md is {line_count} lines (exceeds {warn} line warning threshold)",
                        file_path=file_path,
                    )
                )
        return violations


# ---------------------------------------------------------------------------
# Rule 7: gemini-dead-file-refs
# ---------------------------------------------------------------------------


class GeminiDeadFileRefsRule(Rule):
    @property
    def rule_id(self) -> str:
        return "gemini-dead-file-refs"

    @property
    def description(self) -> str:
        return "Scan GEMINI.md for file path references to non-existent files"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        for file_path in _find_gemini_files(context.root_path):
            content = read_text(file_path)
            if content is None:
                continue
            base_dir = file_path.parent
            in_code_block = False
            for line_num, line in enumerate(content.splitlines(), 1):
                if line.strip().startswith("```"):
                    in_code_block = not in_code_block
                    continue
                if in_code_block:
                    continue
                for m in _FILE_REF_RE.finditer(line):
                    ref = m.group(1)
                    import_match = _IMPORT_RE.match(line)
                    if import_match and ref == import_match.group(1):
                        continue
                    target = (base_dir / ref).resolve()
                    try:
                        target.relative_to(context.root_path.resolve())
                    except ValueError:
                        continue
                    if not target.exists():
                        violations.append(
                            self.violation(
                                f"File reference '{ref}' points to non-existent path",
                                file_path=file_path,
                                line=line_num,
                            )
                        )
        return violations


# ---------------------------------------------------------------------------
# Rule 8: gemini-weak-language
# ---------------------------------------------------------------------------


class GeminiWeakLanguageRule(Rule):
    @property
    def rule_id(self) -> str:
        return "gemini-weak-language"

    @property
    def description(self) -> str:
        return "Detect weak or hedging language in GEMINI.md instructions"

    def default_severity(self) -> Severity:
        return Severity.INFO

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        for file_path in _find_gemini_files(context.root_path):
            content = read_text(file_path)
            if content is None:
                continue
            for line_num, line in enumerate(content.splitlines(), 1):
                for m in _WEAK_RE.finditer(line):
                    violations.append(
                        self.violation(
                            f"Weak language '{m.group()}' — use direct instructions instead",
                            file_path=file_path,
                            line=line_num,
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

        for fpath, file_violations in files.items():
            content = read_text(fpath)
            if content is None:
                continue
            results.append(
                AutofixResult(
                    rule_id=self.rule_id,
                    file_path=fpath,
                    confidence=AutofixConfidence.SUGGEST,
                    original_content=content,
                    fixed_content=content,
                    description="Review and replace weak language with direct instructions",
                    violations_fixed=file_violations,
                )
            )
        return results


# ---------------------------------------------------------------------------
# Rule 9: gemini-tautological
# ---------------------------------------------------------------------------


class GeminiTautologicalRule(Rule):
    @property
    def rule_id(self) -> str:
        return "gemini-tautological"

    @property
    def description(self) -> str:
        return "Detect tautological instructions that restate default AI behavior"

    def default_severity(self) -> Severity:
        return Severity.INFO

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        for file_path in _find_gemini_files(context.root_path):
            content = read_text(file_path)
            if content is None:
                continue
            for line_num, line in enumerate(content.splitlines(), 1):
                for pattern, label in _TAUTOLOGICAL_PATTERNS:
                    if pattern.search(line):
                        violations.append(
                            self.violation(
                                f"Tautological instruction '{label}' — "
                                f"this restates default behavior and wastes context",
                                file_path=file_path,
                                line=line_num,
                            )
                        )
                        break
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

        for fpath, file_violations in files.items():
            content = read_text(fpath)
            if content is None:
                continue
            lines = content.splitlines(True)
            taut_lines = {v.line for v in file_violations if v.line}
            fixed_lines = [l for i, l in enumerate(lines, 1) if i not in taut_lines]
            fixed = "".join(fixed_lines)
            if fixed != content:
                results.append(
                    AutofixResult(
                        rule_id=self.rule_id,
                        file_path=fpath,
                        confidence=AutofixConfidence.SAFE,
                        original_content=content,
                        fixed_content=fixed,
                        description="Removed tautological instructions",
                        violations_fixed=file_violations,
                    )
                )
        return results


# ---------------------------------------------------------------------------
# Rule 10: gemini-critical-position
# ---------------------------------------------------------------------------


class GeminiCriticalPositionRule(Rule):
    @property
    def rule_id(self) -> str:
        return "gemini-critical-position"

    @property
    def description(self) -> str:
        return "Check that critical instructions are positioned at the top of GEMINI.md"

    def default_severity(self) -> Severity:
        return Severity.INFO

    _CRITICAL_MARKERS = re.compile(r"\b(CRITICAL|IMPORTANT|MUST|NEVER|ALWAYS|REQUIRED|MANDATORY)\b")

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        for file_path in _find_gemini_files(context.root_path):
            content = read_text(file_path)
            if content is None:
                continue
            lines = content.splitlines()
            if len(lines) < 20:
                continue
            top_threshold = max(10, len(lines) // 5)
            for line_num, line in enumerate(lines, 1):
                if line_num <= top_threshold:
                    continue
                if self._CRITICAL_MARKERS.search(line):
                    violations.append(
                        self.violation(
                            f"Critical instruction at line {line_num} — "
                            f"move to the top {top_threshold} lines for higher priority",
                            file_path=file_path,
                            line=line_num,
                        )
                    )
                    break
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
            results.append(
                AutofixResult(
                    rule_id=self.rule_id,
                    file_path=v.file_path,
                    confidence=AutofixConfidence.SUGGEST,
                    original_content=content,
                    fixed_content=content,
                    description="Move critical instructions to the top of the file",
                    violations_fixed=[v],
                )
            )
        return results

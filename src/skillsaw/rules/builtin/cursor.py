"""
Rules for validating Cursor .mdc rules files and legacy .cursorrules
"""

import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

from skillsaw.rule import AutofixConfidence, AutofixResult, Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext, HAS_CURSOR
from skillsaw.rules.builtin.utils import read_text, frontmatter_key_line

_VALID_FRONTMATTER_KEYS = {"description", "globs", "alwaysApply"}

_FRONTMATTER_RE = re.compile(r"^---[ \t]*\n(.*?)---[ \t]*\n?", re.DOTALL)

_VAGUE_WORDS = {"general", "misc", "stuff", "various", "other", "todo", "temp", "test"}

_OVERLY_BROAD_GLOBS = {"*", "**", "**/*", "**/**"}


def _parse_mdc_frontmatter(content: str):
    """Parse YAML frontmatter from MDC content.

    Returns (frontmatter_dict, error_message). If no frontmatter is present,
    returns (None, None). If parsing fails, returns (None, error_string).
    """
    if not content.startswith("---"):
        return None, None

    m = _FRONTMATTER_RE.match(content)
    if not m:
        return None, "Unterminated frontmatter (missing closing '---')"

    raw = m.group(1).rstrip("\n")
    try:
        data = yaml.safe_load(raw) if raw else None
    except yaml.YAMLError as e:
        return None, f"Invalid YAML in frontmatter: {e}"

    if data is None:
        return {}, None
    if not isinstance(data, dict):
        return None, "Frontmatter must be a YAML mapping"
    return data, None


def _normalize_globs(value) -> Optional[List[str]]:
    """Normalize globs to a list of pattern strings.

    Accepts a comma-separated string or a list of strings.
    Returns None if the type is unsupported.
    """
    if isinstance(value, str):
        return [p.strip() for p in value.split(",")]
    if isinstance(value, list):
        if all(isinstance(item, str) for item in value):
            return [item.strip() for item in value]
        return None
    return None


def _cursor_rules_dir(context: RepositoryContext) -> Path:
    return context.root_path / ".cursor" / "rules"


def _iter_mdc_files(context: RepositoryContext):
    """Yield (path, content) for each readable .mdc file in .cursor/rules/."""
    rules_dir = _cursor_rules_dir(context)
    if not rules_dir.is_dir():
        return
    for file_path in sorted(rules_dir.rglob("*.mdc")):
        if file_path.is_dir():
            continue
        content = read_text(file_path)
        if content is not None:
            yield file_path, content


def _mdc_body(content: str) -> str:
    """Return the body portion of an MDC file (after frontmatter)."""
    m = _FRONTMATTER_RE.match(content)
    return content[m.end() :] if m else content


def _get_activation_type(frontmatter: Optional[dict]) -> str:
    """Determine the activation type of an MDC rule.

    Returns one of: 'always', 'glob', 'agent-requested', 'manual'.
    """
    if frontmatter is None:
        return "manual"
    if frontmatter.get("alwaysApply") is True:
        return "always"
    globs = frontmatter.get("globs")
    if globs is not None:
        normalized = _normalize_globs(globs)
        if normalized and any(p.strip() for p in normalized):
            return "glob"
    desc = frontmatter.get("description")
    if isinstance(desc, str) and desc.strip():
        return "agent-requested"
    return "manual"


# ---------------------------------------------------------------------------
# Existing monolithic rules (kept for backward compat, default disabled)
# ---------------------------------------------------------------------------


class CursorMdcValidRule(Rule):
    """Validate .cursor/rules/*.mdc files: valid frontmatter, known keys, correct types"""

    repo_types = None
    formats = {HAS_CURSOR}

    @property
    def rule_id(self) -> str:
        return "cursor-mdc-valid"

    @property
    def description(self) -> str:
        return (
            "Cursor .mdc rule files must have valid frontmatter with known keys and correct types"
        )

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def _find_cursor_rules_dir(self, context: RepositoryContext) -> Path:
        return context.root_path / ".cursor" / "rules"

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []

        rules_dir = self._find_cursor_rules_dir(context)
        if not rules_dir.is_dir():
            return violations

        for file_path in sorted(rules_dir.rglob("*")):
            if file_path.is_dir():
                continue

            if file_path.suffix.lower() != ".mdc":
                violations.append(
                    self.violation(
                        f"Non-.mdc file in .cursor/rules/: '{file_path.name}' "
                        f"(only .mdc files are loaded by Cursor)",
                        file_path=file_path,
                        severity=Severity.WARNING,
                    )
                )
                continue

            content = read_text(file_path)
            if content is None:
                violations.append(
                    self.violation(
                        f"Failed to read file: {file_path}",
                        file_path=file_path,
                    )
                )
                continue

            if not content.strip():
                violations.append(
                    self.violation(
                        "Empty .mdc file",
                        file_path=file_path,
                        severity=Severity.WARNING,
                    )
                )
                continue

            frontmatter, error = _parse_mdc_frontmatter(content)
            if error:
                violations.append(self.violation(error, file_path=file_path))
                continue

            if frontmatter is None:
                violations.append(
                    self.violation(
                        "Missing frontmatter: .mdc files require YAML frontmatter "
                        "with at least 'description', 'globs', or 'alwaysApply'",
                        file_path=file_path,
                        severity=Severity.WARNING,
                    )
                )
                continue

            self._check_frontmatter_keys(file_path, frontmatter, violations)
            self._check_description(file_path, frontmatter, violations)
            self._check_globs(file_path, frontmatter, violations)
            self._check_always_apply(file_path, frontmatter, violations)
            self._check_activation(file_path, content, frontmatter, violations)

        return violations

    def _check_frontmatter_keys(
        self,
        file_path: Path,
        frontmatter: dict,
        violations: List[RuleViolation],
    ) -> None:
        unknown_keys = set(frontmatter.keys()) - _VALID_FRONTMATTER_KEYS
        for key in sorted(unknown_keys):
            violations.append(
                self.violation(
                    f"Unknown frontmatter key '{key}'. "
                    f"Valid keys: description, globs, alwaysApply",
                    file_path=file_path,
                    line=frontmatter_key_line(file_path, key),
                    severity=Severity.WARNING,
                )
            )

    def _check_description(
        self,
        file_path: Path,
        frontmatter: dict,
        violations: List[RuleViolation],
    ) -> None:
        if "description" not in frontmatter:
            return

        desc = frontmatter["description"]
        line = frontmatter_key_line(file_path, "description")

        if not isinstance(desc, str):
            violations.append(
                self.violation(
                    f"'description' must be a string, got {type(desc).__name__}",
                    file_path=file_path,
                    line=line,
                )
            )
            return

        if not desc.strip():
            violations.append(
                self.violation(
                    "'description' is empty",
                    file_path=file_path,
                    line=line,
                    severity=Severity.WARNING,
                )
            )

    def _check_globs(
        self,
        file_path: Path,
        frontmatter: dict,
        violations: List[RuleViolation],
    ) -> None:
        if "globs" not in frontmatter:
            return

        globs = frontmatter["globs"]
        line = frontmatter_key_line(file_path, "globs")

        patterns = _normalize_globs(globs)
        if patterns is None:
            violations.append(
                self.violation(
                    f"'globs' must be a string or list of strings, " f"got {type(globs).__name__}",
                    file_path=file_path,
                    line=line,
                )
            )
            return

        if not patterns:
            violations.append(
                self.violation(
                    "'globs' is empty",
                    file_path=file_path,
                    line=line,
                    severity=Severity.WARNING,
                )
            )
            return

        for pattern in patterns:
            if not pattern:
                violations.append(
                    self.violation(
                        "Empty glob pattern in 'globs' value",
                        file_path=file_path,
                        line=line,
                        severity=Severity.WARNING,
                    )
                )

    def _check_always_apply(
        self,
        file_path: Path,
        frontmatter: dict,
        violations: List[RuleViolation],
    ) -> None:
        if "alwaysApply" not in frontmatter:
            return

        value = frontmatter["alwaysApply"]
        line = frontmatter_key_line(file_path, "alwaysApply")

        if not isinstance(value, bool):
            violations.append(
                self.violation(
                    f"'alwaysApply' must be a boolean (true/false), " f"got {type(value).__name__}",
                    file_path=file_path,
                    line=line,
                )
            )

    def _check_activation(
        self,
        file_path: Path,
        content: str,
        frontmatter: dict,
        violations: List[RuleViolation],
    ) -> None:
        always_apply = frontmatter.get("alwaysApply")
        desc = frontmatter.get("description")
        globs = frontmatter.get("globs")

        is_always = always_apply is True
        has_desc = isinstance(desc, str) and desc.strip()
        has_globs = globs is not None and _normalize_globs(globs)

        if not is_always and not has_desc and not has_globs:
            violations.append(
                self.violation(
                    "Rule has no activation method "
                    "(set alwaysApply: true, add a description, or add globs)",
                    file_path=file_path,
                    severity=Severity.WARNING,
                )
            )

        fm_end = _FRONTMATTER_RE.match(content)
        if fm_end:
            body = content[fm_end.end() :]
            if not body.strip():
                violations.append(
                    self.violation(
                        "Rule has frontmatter but no content body",
                        file_path=file_path,
                        severity=Severity.WARNING,
                    )
                )


class CursorRulesDeprecatedRule(Rule):
    """Warn about legacy .cursorrules file (deprecated in favor of .cursor/rules/)"""

    repo_types = None
    formats = {HAS_CURSOR}

    @property
    def rule_id(self) -> str:
        return "cursor-rules-deprecated"

    @property
    def description(self) -> str:
        return "Legacy .cursorrules file is deprecated; migrate to .cursor/rules/*.mdc"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []

        cursorrules = context.root_path / ".cursorrules"
        if not cursorrules.exists():
            return violations

        content = read_text(cursorrules)
        if content is None:
            violations.append(
                self.violation(
                    "Failed to read .cursorrules file",
                    file_path=cursorrules,
                )
            )
            return violations

        if not content.strip():
            violations.append(
                self.violation(
                    ".cursorrules file is empty",
                    file_path=cursorrules,
                )
            )
            return violations

        violations.append(
            self.violation(
                ".cursorrules is deprecated. "
                "Migrate to .cursor/rules/*.mdc for per-rule control, "
                "glob-based auto-attachment, and better organization",
                file_path=cursorrules,
            )
        )

        return violations

    def fix(
        self,
        context: RepositoryContext,
        violations: List[RuleViolation],
    ) -> List[AutofixResult]:
        cursorrules = context.root_path / ".cursorrules"
        content = read_text(cursorrules)
        if content is None or not content.strip():
            return []

        mdc_content = (
            "---\n"
            "description: Migrated from .cursorrules\n"
            "alwaysApply: true\n"
            "---\n\n" + content
        )

        target = _cursor_rules_dir(context) / "migrated-cursorrules.mdc"
        return [
            AutofixResult(
                rule_id=self.rule_id,
                file_path=target,
                confidence=AutofixConfidence.SUGGEST,
                original_content="",
                fixed_content=mdc_content,
                description=(
                    f"Migrate .cursorrules content to {target.relative_to(context.root_path)}"
                ),
                violations_fixed=violations,
            )
        ]


# ---------------------------------------------------------------------------
# 12 deep, focused rules (auto-enabled when .cursor/ exists)
# ---------------------------------------------------------------------------


class CursorMdcFrontmatterRule(Rule):
    """Flag unknown frontmatter keys in .mdc files"""

    repo_types = None

    @property
    def rule_id(self) -> str:
        return "cursor-mdc-frontmatter"

    @property
    def description(self) -> str:
        return "Only 3 valid frontmatter fields: description, globs, alwaysApply"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        for file_path, content in _iter_mdc_files(context):
            frontmatter, error = _parse_mdc_frontmatter(content)
            if error or frontmatter is None:
                continue
            unknown = set(frontmatter.keys()) - _VALID_FRONTMATTER_KEYS
            for key in sorted(unknown):
                violations.append(
                    self.violation(
                        f"Unknown frontmatter key '{key}' (silently ignored by Cursor). "
                        f"Valid keys: description, globs, alwaysApply",
                        file_path=file_path,
                        line=frontmatter_key_line(file_path, key),
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

        for file_path, file_violations in files.items():
            content = read_text(file_path)
            if content is None:
                continue
            m = _FRONTMATTER_RE.match(content)
            if not m:
                continue
            frontmatter, _ = _parse_mdc_frontmatter(content)
            if frontmatter is None:
                continue
            unknown_keys = set(frontmatter.keys()) - _VALID_FRONTMATTER_KEYS
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
                suffix = "\n" if not fixed_fm.endswith("\n") else ""
                fixed_content = "---\n" + fixed_fm + suffix + content[m.end() :]
                results.append(
                    AutofixResult(
                        rule_id=self.rule_id,
                        file_path=file_path,
                        confidence=AutofixConfidence.SAFE,
                        original_content=content,
                        fixed_content=fixed_content,
                        description=f"Remove unknown frontmatter keys from {file_path.name}",
                        violations_fixed=file_violations,
                    )
                )
        return results


class CursorActivationTypeRule(Rule):
    """Warn when .mdc rules have Manual activation (usually unintentional)"""

    repo_types = None

    @property
    def rule_id(self) -> str:
        return "cursor-activation-type"

    @property
    def description(self) -> str:
        return "Warn when .mdc rule activation type is Manual (no frontmatter)"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        for file_path, content in _iter_mdc_files(context):
            frontmatter, error = _parse_mdc_frontmatter(content)
            if error:
                continue
            activation = _get_activation_type(frontmatter)
            if activation == "manual":
                violations.append(
                    self.violation(
                        "Rule has Manual activation (no frontmatter or empty frontmatter). "
                        "Users must @mention this rule to use it. "
                        "Add description, globs, or alwaysApply to auto-activate",
                        file_path=file_path,
                    )
                )
        return violations


class CursorCrlfDetectionRule(Rule):
    """Detect CRLF line endings that break frontmatter parsing"""

    repo_types = None

    @property
    def rule_id(self) -> str:
        return "cursor-crlf-detection"

    @property
    def description(self) -> str:
        return "CRLF line endings break --- frontmatter detection in .mdc files"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        rules_dir = _cursor_rules_dir(context)
        if not rules_dir.is_dir():
            return violations
        for file_path in sorted(rules_dir.rglob("*.mdc")):
            if file_path.is_dir():
                continue
            try:
                raw = file_path.read_bytes()
            except IOError:
                continue
            if b"\r\n" in raw:
                violations.append(
                    self.violation(
                        "File uses CRLF line endings which break frontmatter detection. "
                        "The parser fails to find the closing '---' and treats the "
                        "entire file as body",
                        file_path=file_path,
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
            try:
                raw = v.file_path.read_bytes()
            except IOError:
                continue
            fixed = raw.replace(b"\r\n", b"\n")
            results.append(
                AutofixResult(
                    rule_id=self.rule_id,
                    file_path=v.file_path,
                    confidence=AutofixConfidence.SAFE,
                    original_content=raw.decode("utf-8", errors="replace"),
                    fixed_content=fixed.decode("utf-8", errors="replace"),
                    description=f"Convert {v.file_path.name} from CRLF to LF",
                    violations_fixed=[v],
                )
            )
        return results


class CursorGlobValidRule(Rule):
    """Validate glob patterns in .mdc files"""

    repo_types = None

    @property
    def rule_id(self) -> str:
        return "cursor-glob-valid"

    @property
    def description(self) -> str:
        return "Validate glob patterns: catch invalid syntax and overly broad patterns"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        for file_path, content in _iter_mdc_files(context):
            frontmatter, error = _parse_mdc_frontmatter(content)
            if error or frontmatter is None or "globs" not in frontmatter:
                continue
            patterns = _normalize_globs(frontmatter["globs"])
            if patterns is None:
                continue
            line = frontmatter_key_line(file_path, "globs")
            for pattern in patterns:
                pattern = pattern.strip()
                if not pattern:
                    continue
                if pattern in _OVERLY_BROAD_GLOBS:
                    violations.append(
                        self.violation(
                            f"Overly broad glob '{pattern}' matches everything, "
                            f"defeating the purpose of glob-based activation",
                            file_path=file_path,
                            line=line,
                        )
                    )
                if self._has_bad_syntax(pattern):
                    violations.append(
                        self.violation(
                            f"Glob pattern '{pattern}' has invalid syntax "
                            f"(unmatched brackets or bad escape)",
                            file_path=file_path,
                            line=line,
                            severity=Severity.ERROR,
                        )
                    )
        return violations

    @staticmethod
    def _has_bad_syntax(pattern: str) -> bool:
        depth = 0
        i = 0
        while i < len(pattern):
            ch = pattern[i]
            if ch == "\\" and i + 1 < len(pattern):
                i += 2
                continue
            if ch == "[":
                depth += 1
            elif ch == "]":
                if depth > 0:
                    depth -= 1
                else:
                    return True
            i += 1
        return depth != 0


class CursorEmptyBodyRule(Rule):
    """Detect .mdc files with frontmatter but no content body"""

    repo_types = None

    @property
    def rule_id(self) -> str:
        return "cursor-empty-body"

    @property
    def description(self) -> str:
        return "Rule file has frontmatter but empty body — the rule has no content"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        for file_path, content in _iter_mdc_files(context):
            frontmatter, error = _parse_mdc_frontmatter(content)
            if error or frontmatter is None:
                continue
            body = _mdc_body(content)
            if not body.strip():
                violations.append(
                    self.violation(
                        "Rule has frontmatter but no content body. "
                        "Add instructions for the rule to be useful",
                        file_path=file_path,
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
            stem = v.file_path.stem
            template = f"\n# {stem}\n\nTODO: Add rule instructions here.\n"
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
        return results


class CursorDescriptionQualityRule(Rule):
    """Check description quality for agent-requested rules"""

    repo_types = None

    @property
    def rule_id(self) -> str:
        return "cursor-description-quality"

    @property
    def description(self) -> str:
        return "Agent-requested rules need clear descriptions (the agent's only signal)"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        for file_path, content in _iter_mdc_files(context):
            frontmatter, error = _parse_mdc_frontmatter(content)
            if error or frontmatter is None:
                continue
            activation = _get_activation_type(frontmatter)
            if activation != "agent-requested":
                continue
            desc = frontmatter.get("description", "")
            if not isinstance(desc, str):
                continue
            line = frontmatter_key_line(file_path, "description")
            desc_stripped = desc.strip()
            if not desc_stripped:
                violations.append(
                    self.violation(
                        "Agent-requested rule has empty description. "
                        "The agent uses the description to decide whether to load this rule",
                        file_path=file_path,
                        line=line,
                    )
                )
                continue
            if len(desc_stripped) < 10:
                violations.append(
                    self.violation(
                        f"Description is only {len(desc_stripped)} chars — too short "
                        f"for the agent to understand when to load this rule",
                        file_path=file_path,
                        line=line,
                    )
                )
            words_lower = set(desc_stripped.lower().split())
            vague = words_lower & _VAGUE_WORDS
            if vague:
                violations.append(
                    self.violation(
                        f"Description uses vague language ({', '.join(sorted(vague))}). "
                        f"Be specific about when this rule should apply",
                        file_path=file_path,
                        line=line,
                    )
                )
        return violations


class CursorGlobOverlapRule(Rule):
    """Detect overlapping glob patterns across .mdc files"""

    repo_types = None

    @property
    def rule_id(self) -> str:
        return "cursor-glob-overlap"

    @property
    def description(self) -> str:
        return "Warn when multiple .mdc files have overlapping glob patterns"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        pattern_map: Dict[str, List[Tuple[Path, int]]] = {}

        for file_path, content in _iter_mdc_files(context):
            frontmatter, error = _parse_mdc_frontmatter(content)
            if error or frontmatter is None or "globs" not in frontmatter:
                continue
            patterns = _normalize_globs(frontmatter["globs"])
            if patterns is None:
                continue
            line = frontmatter_key_line(file_path, "globs")
            for p in patterns:
                p = p.strip()
                if p:
                    pattern_map.setdefault(p, []).append((file_path, line))

        reported = set()
        for pattern, locations in pattern_map.items():
            if len(locations) < 2:
                continue
            names = sorted(set(fp.name for fp, _ in locations))
            for file_path, line in locations:
                key = (file_path, pattern)
                if key in reported:
                    continue
                reported.add(key)
                others = [n for n in names if n != file_path.name]
                if others:
                    violations.append(
                        self.violation(
                            f"Glob '{pattern}' also used by: {', '.join(others)}. "
                            f"Both rules will fire on matching files",
                            file_path=file_path,
                            line=line,
                        )
                    )
        return violations


class CursorRuleSizeRule(Rule):
    """Warn when a single .mdc rule file is too large"""

    repo_types = None
    config_schema = {
        "max-lines": {
            "type": "integer",
            "default": 500,
            "description": "Maximum lines before warning",
        }
    }

    @property
    def rule_id(self) -> str:
        return "cursor-rule-size"

    @property
    def description(self) -> str:
        return "Warn when a rule file exceeds 500 lines (wastes context budget)"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        max_lines = self.config.get("max-lines", 500)
        for file_path, content in _iter_mdc_files(context):
            line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
            if line_count > max_lines:
                violations.append(
                    self.violation(
                        f"Rule file is {line_count} lines (max {max_lines}). "
                        f"Large rules waste context budget on every interaction",
                        file_path=file_path,
                    )
                )
        return violations


class CursorFrontmatterTypesRule(Rule):
    """Validate frontmatter field types and coerce when possible"""

    repo_types = None

    @property
    def rule_id(self) -> str:
        return "cursor-frontmatter-types"

    @property
    def description(self) -> str:
        return "alwaysApply must be boolean, globs must be string or list"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        for file_path, content in _iter_mdc_files(context):
            frontmatter, error = _parse_mdc_frontmatter(content)
            if error or frontmatter is None:
                continue

            if "alwaysApply" in frontmatter:
                val = frontmatter["alwaysApply"]
                if not isinstance(val, bool):
                    line = frontmatter_key_line(file_path, "alwaysApply")
                    violations.append(
                        self.violation(
                            f"'alwaysApply' must be boolean (true/false), "
                            f"got {type(val).__name__}: {val!r}",
                            file_path=file_path,
                            line=line,
                        )
                    )

            if "globs" in frontmatter:
                val = frontmatter["globs"]
                if not isinstance(val, (str, list)):
                    line = frontmatter_key_line(file_path, "globs")
                    violations.append(
                        self.violation(
                            f"'globs' must be string or list, "
                            f"got {type(val).__name__}: {val!r}",
                            file_path=file_path,
                            line=line,
                        )
                    )
                elif isinstance(val, list) and not all(isinstance(i, str) for i in val):
                    line = frontmatter_key_line(file_path, "globs")
                    violations.append(
                        self.violation(
                            "'globs' list items must all be strings",
                            file_path=file_path,
                            line=line,
                        )
                    )

            if "description" in frontmatter:
                val = frontmatter["description"]
                if not isinstance(val, str):
                    line = frontmatter_key_line(file_path, "description")
                    violations.append(
                        self.violation(
                            f"'description' must be a string, "
                            f"got {type(val).__name__}: {val!r}",
                            file_path=file_path,
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
        files: Dict[Path, List[RuleViolation]] = {}
        for v in violations:
            if v.file_path:
                files.setdefault(v.file_path, []).append(v)

        for file_path, file_violations in files.items():
            content = read_text(file_path)
            if content is None:
                continue
            frontmatter, error = _parse_mdc_frontmatter(content)
            if error or frontmatter is None:
                continue

            m = _FRONTMATTER_RE.match(content)
            if not m:
                continue
            fm_text = m.group(1)
            fixed_fm = fm_text

            if "alwaysApply" in frontmatter and not isinstance(frontmatter["alwaysApply"], bool):
                val = frontmatter["alwaysApply"]
                bool_val = str(val).lower() in ("true", "1", "yes")
                fixed_fm = re.sub(
                    r"^(alwaysApply\s*:\s*).*$",
                    rf"\g<1>{'true' if bool_val else 'false'}",
                    fixed_fm,
                    flags=re.MULTILINE,
                )

            if "globs" in frontmatter and isinstance(frontmatter["globs"], (int, float)):
                fixed_fm = re.sub(
                    r"^(globs\s*:\s*)(.*)$",
                    lambda match: f"{match.group(1)}'{match.group(2).strip()}'",
                    fixed_fm,
                    flags=re.MULTILINE,
                )

            if fixed_fm != fm_text:
                fixed_content = "---\n" + fixed_fm + content[m.end() :]
                results.append(
                    AutofixResult(
                        rule_id=self.rule_id,
                        file_path=file_path,
                        confidence=AutofixConfidence.SAFE,
                        original_content=content,
                        fixed_content=fixed_content,
                        description=f"Coerce frontmatter types in {file_path.name}",
                        violations_fixed=file_violations,
                    )
                )
        return results


class CursorDuplicateRulesRule(Rule):
    """Detect .mdc files with nearly identical bodies"""

    repo_types = None
    config_schema = {
        "similarity-threshold": {
            "type": "float",
            "default": 0.8,
            "description": "Minimum similarity ratio (0-1) to flag as duplicate",
        }
    }

    @property
    def rule_id(self) -> str:
        return "cursor-duplicate-rules"

    @property
    def description(self) -> str:
        return "Detect .mdc files with >80% similar bodies — suggest consolidation"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        threshold = self.config.get("similarity-threshold", 0.8)

        bodies: List[Tuple[Path, str]] = []
        for file_path, content in _iter_mdc_files(context):
            body = _mdc_body(content).strip()
            if body:
                bodies.append((file_path, body))

        reported: set = set()
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
                            f"Rule body is {pct}% similar to {path_b.name}. "
                            f"Consider consolidating into a single rule",
                            file_path=path_a,
                        )
                    )
        return violations


class CursorAlwaysApplyOveruseRule(Rule):
    """Warn when too many rules have alwaysApply: true"""

    repo_types = None
    config_schema = {
        "max-always-apply": {
            "type": "integer",
            "default": 3,
            "description": "Maximum number of rules with alwaysApply: true before warning",
        }
    }

    @property
    def rule_id(self) -> str:
        return "cursor-always-apply-overuse"

    @property
    def description(self) -> str:
        return "Warn when >3 rules have alwaysApply: true (context budget)"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        max_count = self.config.get("max-always-apply", 3)
        always_on: List[Tuple[Path, int]] = []

        for file_path, content in _iter_mdc_files(context):
            frontmatter, error = _parse_mdc_frontmatter(content)
            if error or frontmatter is None:
                continue
            if frontmatter.get("alwaysApply") is True:
                line = frontmatter_key_line(file_path, "alwaysApply")
                always_on.append((file_path, line))

        if len(always_on) > max_count:
            names = [fp.name for fp, _ in always_on]
            for file_path, line in always_on:
                violations.append(
                    self.violation(
                        f"{len(always_on)} rules have alwaysApply: true "
                        f"(max recommended: {max_count}). "
                        f"Every always-on rule burns context budget on every interaction. "
                        f"Files: {', '.join(names)}",
                        file_path=file_path,
                        line=line,
                    )
                )
        return violations

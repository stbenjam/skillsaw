"""
Base classes for linting rules
"""

import difflib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional, Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .context import RepositoryContext
    from .rules.builtin.content_analysis import (
        ContentBlock,
        FileContentBlock,
        FrontmatteredBlock,
        BodyContent,
    )


class Severity(Enum):
    """Rule violation severity levels"""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class AutofixConfidence(Enum):
    SAFE = "safe"
    SUGGEST = "suggest"
    LLM = "llm"


@dataclass
class RuleViolation:
    """Represents a rule violation"""

    rule_id: str
    severity: Severity
    message: str
    file_path: Optional[Path] = None
    line: Optional[int] = None
    block: Optional["ContentBlock"] = field(default=None, repr=False)
    source: str = "builtin"
    value: Optional[float] = None

    def __post_init__(self):
        if self.block is None and self.file_path is not None:
            from .rules.builtin.content_analysis import FileContentBlock

            self.block = FileContentBlock(path=self.file_path, category="file")
        if self.file_path is None and self.block is not None:
            self.file_path = self.block.path

    @property
    def file_line(self) -> Optional[int]:
        """File line number, translated through block offset if available."""
        if self.block is not None and self.line is not None:
            return self.block.file_line(self.line)
        return self.line

    def __str__(self):
        """Format violation for display"""
        icon = {Severity.ERROR: "✗", Severity.WARNING: "⚠", Severity.INFO: "ℹ"}[self.severity]

        location = ""
        display_line = self.file_line
        if self.file_path:
            location = f" [{self.file_path}]"
            if display_line:
                location = f" [{self.file_path}:{display_line}]"

        return f"{icon} {self.severity.value.upper()}{location}: {self.message}"


@dataclass
class FixOp(ABC):
    """Base class for autofix operations on tree nodes."""

    rule_id: str
    confidence: AutofixConfidence
    description: str
    violations_fixed: List[RuleViolation] = field(default_factory=list)

    @property
    @abstractmethod
    def target_path(self) -> Path:
        """File path affected by this fix, used for conflict detection."""
        ...

    @abstractmethod
    def apply(self) -> None:
        """Write the fix to disk through the appropriate node method."""
        ...

    @abstractmethod
    def diff(self, root: Optional[Path] = None) -> str:
        """Produce a unified diff string for dry-run display."""
        ...


@dataclass
class FrontmatterFix(FixOp):
    """Fix scoped to a FrontmatteredBlock's frontmatter YAML."""

    block: Optional["FrontmatteredBlock"] = field(default=None, repr=False)
    original_fm: str = ""
    fixed_fm: str = ""

    @property
    def target_path(self) -> Path:
        return self.block.path

    def apply(self) -> None:
        self.block.write_frontmatter_text(self.fixed_fm)

    def diff(self, root: Optional[Path] = None) -> str:
        body = self.block.body_text or ""
        old = f"---\n{self.original_fm}\n---\n{body}" if self.original_fm else body
        new = f"---\n{self.fixed_fm}\n---\n{body}"
        return _unified_diff(old, new, self.block.path, root)


@dataclass
class BodyFix(FixOp):
    """Fix scoped to a BodyContent node's markdown body."""

    block: Optional["BodyContent"] = field(default=None, repr=False)
    original_body: str = ""
    fixed_body: str = ""

    @property
    def target_path(self) -> Path:
        return self.block.path

    def apply(self) -> None:
        self.block.write_body(self.fixed_body)

    def diff(self, root: Optional[Path] = None) -> str:
        from .rules.builtin.content_analysis import FrontmatteredBlock

        parent = self.block.parent
        if isinstance(parent, FrontmatteredBlock):
            fm = parent.read_frontmatter_text()
            prefix = f"---\n{fm}\n---\n" if fm else ""
        else:
            prefix = ""
        old = prefix + self.original_body
        new = prefix + self.fixed_body
        return _unified_diff(old, new, self.block.path, root)


@dataclass
class FileFix(FixOp):
    """File-level fix for JSON, file creation, or files without block structure."""

    file_path: Path = field(default_factory=lambda: Path())
    original_content: str = ""
    fixed_content: str = ""

    @property
    def target_path(self) -> Path:
        return self.file_path

    def apply(self) -> None:
        from .rules.builtin.utils import invalidate_read_caches

        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.file_path.write_text(self.fixed_content, encoding="utf-8")
        invalidate_read_caches(self.file_path)

    def diff(self, root: Optional[Path] = None) -> str:
        return _unified_diff(self.original_content, self.fixed_content, self.file_path, root)


@dataclass
class RenameFix(FixOp):
    """File rename operation."""

    file_path: Path = field(default_factory=lambda: Path())
    rename_from: Path = field(default_factory=lambda: Path())
    content: str = ""

    @property
    def target_path(self) -> Path:
        return self.file_path

    def apply(self) -> None:
        from .rules.builtin.utils import invalidate_read_caches

        src, dst = self.rename_from, self.file_path
        if not src.exists():
            raise FileNotFoundError(f"Rename source does not exist: {src}")
        same_file = src.resolve() == dst.resolve()
        if dst.exists() and not same_file:
            raise FileExistsError(f"Rename target already exists: {dst}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        invalidate_read_caches(src)
        invalidate_read_caches(dst)

    def diff(self, root: Optional[Path] = None) -> str:
        return ""


def _unified_diff(old: str, new: str, path: Path, root: Optional[Path] = None) -> str:
    try:
        rel = str(path.relative_to(root)) if root else str(path)
    except ValueError:
        rel = str(path)
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{rel}",
            tofile=f"b/{rel}",
        )
    )


AutofixResult = FileFix


class Rule(ABC):
    """Base class for linting rules"""

    repo_types = None
    formats = None
    config_schema = {}
    since = "0.1.0"
    autofix_confidence: Optional["AutofixConfidence"] = None
    _source: str = "builtin"
    baseline_mode: Optional[str] = None  # "ceiling" or "floor"

    def __init__(self, config: Dict[str, Any] = None):
        """
        Initialize rule with optional configuration

        Args:
            config: Rule-specific configuration from .skillsaw.yaml
        """
        self.config = config or {}
        self._enabled = self.config.get("enabled", True)

        # Get severity from config or use default
        severity_str = self.config.get("severity", self.default_severity().value)
        if severity_str is None:
            self._severity = self.default_severity()
        else:
            try:
                self._severity = Severity(severity_str)
            except (ValueError, KeyError, TypeError) as err:
                valid = ", ".join(s.value for s in Severity)
                raise ValueError(
                    f"Invalid severity '{severity_str}' for rule '{self.rule_id}'. "
                    f"Valid values: {valid}"
                ) from err

    @property
    @abstractmethod
    def rule_id(self) -> str:
        """Unique identifier for this rule (e.g., 'plugin-json-required')"""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description of what this rule checks"""
        pass

    @abstractmethod
    def default_severity(self) -> Severity:
        """Default severity level for this rule"""
        pass

    @property
    def enabled(self) -> bool:
        """Check if rule is enabled"""
        return self._enabled

    @property
    def severity(self) -> Severity:
        """Get configured severity level"""
        return self._severity

    @abstractmethod
    def check(self, context: "RepositoryContext") -> List[RuleViolation]:
        """
        Execute the rule check

        Args:
            context: Repository context with paths and metadata

        Returns:
            List of violations found
        """
        pass

    def fix(
        self,
        context: "RepositoryContext",
        violations: List[RuleViolation],
        *,
        provider: Any = None,
    ) -> List[FixOp]:
        """Attempt to fix violations.

        Override in subclasses.  ``provider`` is an optional
        ``CompletionProvider`` for LLM-assisted fixes.
        """
        return []

    @property
    def supports_autofix(self) -> bool:
        return type(self).fix is not Rule.fix

    @property
    def llm_fix_prompt(self) -> Optional[str]:
        return None

    @property
    def llm_fix_frontmatter(self) -> bool:
        """When True, LLM fix operates on frontmatter YAML only (not the body)."""
        return False

    def frontmatter_fix(
        self,
        block: "FrontmatteredBlock",
        original_fm: str,
        fixed_fm: str,
        description: str,
        violations: List[RuleViolation],
        confidence: AutofixConfidence = None,
    ) -> FrontmatterFix:
        return FrontmatterFix(
            rule_id=self.rule_id,
            confidence=confidence or self.autofix_confidence,
            description=description,
            violations_fixed=violations,
            block=block,
            original_fm=original_fm,
            fixed_fm=fixed_fm,
        )

    def body_fix(
        self,
        block: "BodyContent",
        original_body: str,
        fixed_body: str,
        description: str,
        violations: List[RuleViolation],
        confidence: AutofixConfidence = None,
    ) -> BodyFix:
        return BodyFix(
            rule_id=self.rule_id,
            confidence=confidence or self.autofix_confidence,
            description=description,
            violations_fixed=violations,
            block=block,
            original_body=original_body,
            fixed_body=fixed_body,
        )

    def file_fix(
        self,
        file_path: Path,
        original_content: str,
        fixed_content: str,
        description: str,
        violations: List[RuleViolation],
        confidence: AutofixConfidence = None,
    ) -> FileFix:
        return FileFix(
            rule_id=self.rule_id,
            confidence=confidence or self.autofix_confidence,
            description=description,
            violations_fixed=violations,
            file_path=file_path,
            original_content=original_content,
            fixed_content=fixed_content,
        )

    def rename_fix(
        self,
        file_path: Path,
        rename_from: Path,
        description: str,
        violations: List[RuleViolation],
        confidence: AutofixConfidence = None,
    ) -> RenameFix:
        return RenameFix(
            rule_id=self.rule_id,
            confidence=confidence or self.autofix_confidence,
            description=description,
            violations_fixed=violations,
            file_path=file_path,
            rename_from=rename_from,
        )

    def violation(
        self,
        message: str,
        file_path: Path = None,
        line: int = None,
        severity: Severity = None,
        block: "ContentBlock" = None,
        value: float = None,
    ) -> RuleViolation:
        """Create a violation for this rule.

        Pass ``block`` for content-based violations.  ``file_path`` is
        accepted for backward compatibility and auto-wraps into a block.
        """
        return RuleViolation(
            rule_id=self.rule_id,
            severity=severity if severity is not None else self.severity,
            message=message,
            file_path=file_path,
            line=line,
            block=block,
            source=self._source,
            value=value,
        )

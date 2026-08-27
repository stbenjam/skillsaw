"""
Base classes for linting rules
"""

import copy
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, List, Optional, Dict, Any, Type, TypeVar, TYPE_CHECKING

if TYPE_CHECKING:
    from .context import RepositoryContext
    from .blocks import ContentBlock
    from .lint_target import LintTarget

TargetT = TypeVar("TargetT", bound="LintTarget")


class Severity(Enum):
    """Rule violation severity levels"""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class AutofixConfidence(Enum):
    SAFE = "safe"
    SUGGEST = "suggest"


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
    # Optional discriminator for rules that emit more than one ratchet
    # (value-carrying) violation per file, so their baseline fingerprints
    # don't collide. Example: context-budget emits whole-file and
    # per-description token violations for the same SKILL.md.
    metric: Optional[str] = None
    # Whether ``skillsaw fix`` can resolve this violation. None means
    # unknown — e.g. synthetic violations constructed outside
    # ``Rule.violation()``.
    fixable: Optional[bool] = None
    # Confidence of the fix when ``fixable``: SAFE fixes apply with plain
    # ``skillsaw fix``, SUGGEST fixes require ``--suggest``.
    fix_confidence: Optional["AutofixConfidence"] = None
    # Stable suffix for external and baseline identities when a rule emits
    # sibling findings at the same path and line. Rules should set this from
    # their first release so existing external fingerprints never churn.
    fingerprint_discriminator: Optional[str] = None

    def __post_init__(self):
        if self.block is None and self.file_path is not None:
            # Lazy: importing ``skillsaw.blocks`` pulls in ``rules.builtin``
            # (via utils), whose package __init__ imports rule modules that
            # import this module — so the import must happen after ``rule`` is
            # fully loaded, not at module top.
            from .blocks import FileContentBlock

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
class AutofixResult:
    rule_id: str
    file_path: Path
    confidence: AutofixConfidence
    original_content: str
    fixed_content: str
    description: str
    violations_fixed: List[RuleViolation] = field(default_factory=list)
    rename_from: Optional[Path] = None
    # Side effect to run only when the fix is actually applied (never on
    # dry-run). Rules must not mutate repository state inside fix() itself —
    # fix() is also called for previews.
    on_apply: Optional[Callable[[], None]] = field(default=None, repr=False, compare=False)


class Rule(ABC):
    """Base class for linting rules"""

    repo_types = None
    formats = None
    config_schema = {}
    # Third-party rules with a partially migrated config_schema can set this
    # to False: declared options are still type-checked, while undeclared
    # options remain accepted during the migration.
    strict_options = True
    since = "0.1.0"
    # Former rule IDs this rule was known by. Aliases resolve to the
    # canonical ``rule_id`` everywhere a rule is named: config keys,
    # --rule / --skip-rule, inline suppression directives, baseline
    # matching, and ``skillsaw explain``.
    aliases: tuple = ()
    # Version in which the rule was deprecated (e.g. "0.18.0"); None means
    # active. A deprecated rule no longer runs under ``enabled: auto`` —
    # it only runs when a config sets ``enabled: true`` or a --rule flag
    # names it — and naming it anywhere emits a warning that the rule
    # will be removed in a future release.
    deprecated: Optional[str] = None
    # Rule ID that supersedes this one, named in deprecation messages.
    replaced_by: Optional[str] = None
    # One-sentence rationale rendered on the documentation site's
    # Deprecated page and each deprecated rule's own page.
    deprecated_reason: Optional[str] = None
    # Default activation when the user config doesn't mention the rule:
    # True (always on), False (opt-in), or "auto" (on when repo_types /
    # formats match the repository). ``LinterConfig.default()`` is generated
    # from this, so the class is the single source of truth. Per project
    # policy new rules must use "auto" or False — never True.
    default_enabled: Any = "auto"
    # Which ecosystem's format conventions this rule enforces. None (the
    # default) means ecosystem-neutral — content and security rules read
    # every block whoever owns it. "claude" makes scoped_find() drop
    # nodes whose provenance_dir() is claimed exclusively by other
    # ecosystems, so a Codex-only plugin is exempt from Claude manifest,
    # frontmatter, and naming requirements. Dual-manifest and unclaimed
    # directories stay in scope. Conditional-strictness rules (the
    # ecosystem-tightened hooks/MCP shape checks) stay None and consult
    # RepositoryContext.in_codex_only_plugin() instead — tightening is
    # their semantic, not a skip.
    provenance_scope: Optional[str] = None
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

    def setting(self, name: str) -> Any:
        """Resolve a config option: the user's override, else the schema default.

        Only options declared in ``config_schema`` can be read — an undeclared
        name raises ``KeyError`` so a read/declaration mismatch fails fast in
        development. An explicit ``null`` in config resolves to the default.
        Mutable (list/dict) values — overrides as well as defaults — are
        returned as copies so callers can neither corrupt the shared schema
        nor mutate the user's config in place. An int override for a
        float/number-typed option is coerced to float; any other user value
        is returned unchanged.
        """
        try:
            entry = self.config_schema[name]
        except KeyError:
            # Mirrors linter.UNIVERSAL_RULE_OPTION_KEYS (kept literal to
            # avoid a module cycle; pinned by a test). The universal keys
            # are reserved: declare one in config_schema to read it here.
            if name in ("enabled", "severity", "exclude"):
                raise KeyError(
                    f"rule '{self.rule_id}' does not declare universal key '{name}' "
                    "in its config_schema — read 'enabled'/'severity' via "
                    "self.enabled / self.severity; per-rule 'exclude' is applied "
                    f"by the linter. Declare '{name}' in config_schema to also "
                    "read it here."
                ) from None
            raise KeyError(f"rule '{self.rule_id}' has no config_schema option '{name}'") from None
        if not isinstance(entry, dict):
            raise ValueError(
                f"config_schema option '{name}' for rule '{self.rule_id}' must be a mapping"
            )
        if "default" not in entry:
            raise ValueError(
                f"config_schema option '{name}' for rule '{self.rule_id}' is missing 'default'"
            )
        value = self.config.get(name)
        if value is None:
            value = entry["default"]
        # Coercion applies to defaults too: {"type": "float", "default": 1}
        # must read the same configured or not.
        if (
            entry.get("type") in ("float", "number")
            and isinstance(value, int)
            and not isinstance(value, bool)
        ):
            return float(value)
        if isinstance(value, (list, dict)):
            return copy.deepcopy(value)
        return value

    @property
    @abstractmethod
    def rule_id(self) -> str:
        """Unique identifier for this rule (e.g., 'claude-plugin-json-required')"""
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

    def scoped_find(self, context: "RepositoryContext", node_type: Type[TargetT]) -> List[TargetT]:
        """``context.lint_tree.find(node_type)``, filtered to this rule's
        :attr:`provenance_scope`.

        The one place format-scope filtering happens: a format rule
        declares which ecosystem's conventions it enforces and iterates
        its targets through this helper — never with an inline ownership
        guard in the rule body. The ownership question itself is answered
        by ``RepositoryContext.in_format_scope``, a view over the cached
        :class:`PluginProvenance` record.

        Memoized like ``find()`` itself: the scope depends only on the
        ecosystem and the static tree, so every rule declaring the same
        scope shares one filtered list rather than re-running the filter
        per rule, per node.
        """
        if self.provenance_scope is None:
            return context.lint_tree.find(node_type)
        ecosystem = self.provenance_scope
        return context.lint_tree.find_filtered(
            node_type,
            ("provenance_scope", ecosystem),
            lambda node: context.in_format_scope(node, ecosystem),
        )

    def fix(
        self,
        context: "RepositoryContext",
        violations: List[RuleViolation],
    ) -> List[AutofixResult]:
        """Attempt to fix violations.  Override in subclasses."""
        return []

    @property
    def supports_autofix(self) -> bool:
        return type(self).fix is not Rule.fix

    def violation(
        self,
        message: str,
        file_path: Optional[Path] = None,
        line: Optional[int] = None,
        severity: Optional[Severity] = None,
        block: Optional["ContentBlock"] = None,
        value: Optional[float] = None,
        metric: Optional[str] = None,
        fixable: Optional[bool] = None,
        fix_confidence: Optional[AutofixConfidence] = None,
        fingerprint_discriminator: Optional[str] = None,
    ) -> RuleViolation:
        """Create a violation for this rule.

        Pass ``block`` for content-based violations.  ``file_path`` is
        accepted for backward compatibility and auto-wraps into a block.
        ``metric`` disambiguates multiple ratchet violations per file.
        ``fingerprint_discriminator`` disambiguates sibling findings at the
        same path and line without changing identities for other rules.

        ``fixable`` defaults from the rule: True when the rule overrides
        ``fix()`` and declares a class-level ``autofix_confidence``.  Rules
        whose ``fix()`` only repairs a subset of their violations must pass
        ``fixable`` explicitly so lint output doesn't over-promise.
        """
        if fixable is None:
            fixable = self.supports_autofix and self.autofix_confidence is not None
        if fix_confidence is None and fixable:
            # Unknown confidence falls back to SUGGEST so every fixable
            # violation carries one and no format over-promises what a
            # plain `skillsaw fix` run will clear.
            fix_confidence = self.autofix_confidence or AutofixConfidence.SUGGEST
        return RuleViolation(
            rule_id=self.rule_id,
            severity=severity if severity is not None else self.severity,
            message=message,
            file_path=file_path,
            line=line,
            block=block,
            source=self._source,
            value=value,
            metric=metric,
            fixable=fixable,
            fix_confidence=fix_confidence,
            fingerprint_discriminator=fingerprint_discriminator,
        )

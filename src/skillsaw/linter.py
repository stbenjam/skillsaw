"""
Main linter orchestration
"""

from __future__ import annotations

import hashlib
import importlib.util
import logging
import re
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, TYPE_CHECKING

logger = logging.getLogger(__name__)

from .rule import Rule, RuleViolation, Severity, AutofixResult, AutofixConfidence
from .context import RepositoryContext
from .config import LinterConfig
from .suppression import build_suppression_map_for_file, SuppressionMap

if TYPE_CHECKING:
    from .baseline import BaselineFile, BaselineEntry


class Linter:
    """
    Main linter that orchestrates rule checking
    """

    def __init__(
        self,
        context: RepositoryContext,
        config: LinterConfig = None,
        rule_ids: Optional[Set[str]] = None,
        skip_rule_ids: Optional[Set[str]] = None,
        baseline: Optional["BaselineFile"] = None,
        no_custom_rules: bool = False,
    ):
        self.context = context
        self.config = config or LinterConfig.default()
        self._rule_ids = rule_ids
        self._skip_rule_ids = skip_rule_ids or set()
        self._baseline = baseline
        self._no_custom_rules = no_custom_rules
        self._stale_baseline_entries: List["BaselineEntry"] = []
        self._baseline_suppressed_count: int = 0
        # Prefer contexts constructed with the config's filters (see
        # RepositoryContext.__init__); only reconfigure when a legacy caller
        # passed a bare context that disagrees with the config.
        # apply_excludes() refreshes derived state (detected_formats, cached
        # lint tree), so this path cannot leave the context stale — but it
        # only narrows: it won't rediscover paths an earlier filter removed.
        if (
            self.context.content_paths != self.config.content_paths
            or self.context.exclude_patterns != self.config.exclude_patterns
        ):
            self.context.content_paths = self.config.content_paths
            self.context.exclude_patterns = self.config.exclude_patterns
            self.context.apply_excludes()
        self.rules: List[Rule] = []
        self._load_rules()

        if self._rule_ids:
            unknown = self._rule_ids - self._known_rule_ids
            if unknown:
                formatted = ", ".join(sorted(unknown))
                raise ValueError(f"Unknown rule(s): {formatted}")

        # A typo in --skip-rule must not silently leave the rule running.
        if self._skip_rule_ids:
            unknown = self._skip_rule_ids - self._known_rule_ids
            if unknown:
                formatted = ", ".join(sorted(unknown))
                raise ValueError(f"Unknown rule(s) in --skip-rule: {formatted}")

    def _load_rules(self):
        """Load all enabled rules"""
        self._known_rule_ids: set = set()

        # Load builtin rules
        self._load_builtin_rules()

        if not self._no_custom_rules:
            for custom_rule_path in self.config.custom_rules:
                self._load_custom_rule(custom_rule_path)

    def _load_builtin_rules(self):
        """Load builtin rules from skillsaw.rules.builtin"""
        from .rules.builtin import BUILTIN_RULES

        for rule_class in BUILTIN_RULES:
            rule_instance = rule_class()
            self._known_rule_ids.add(rule_instance.rule_id)
            if self._rule_ids and rule_instance.rule_id not in self._rule_ids:
                continue
            if rule_instance.rule_id in self._skip_rule_ids:
                logger.info("Rule %-30s skipped (--skip-rule)", rule_instance.rule_id)
                continue
            config = self.config.get_rule_config(rule_instance.rule_id)
            if config:
                rule_instance = rule_class(config)

            if self._rule_ids or self.config.is_rule_enabled(
                rule_instance.rule_id,
                self.context,
                rule_instance.repo_types,
                rule_instance.formats,
                since_version=rule_instance.since,
            ):
                self.rules.append(rule_instance)
                logger.info("Rule %-30s enabled", rule_instance.rule_id)
            else:
                logger.info("Rule %-30s skipped (not applicable)", rule_instance.rule_id)

    def _load_custom_rule(self, rule_path: str):
        """
        Load a custom rule from a Python file

        Args:
            rule_path: Path to Python file containing Rule subclass
        """
        path = Path(rule_path)
        if not path.is_absolute():
            base = self.config.config_dir or self.context.root_path
            path = base / path
        path = path.resolve()

        if not path.exists():
            raise ValueError(f"Custom rule file not found: {path}")

        logger.info("Loading custom rules from %s", path)

        # Unique module name per file so two custom rule files cannot clobber
        # each other in ``sys.modules`` (they previously all loaded as
        # ``custom_rule``).
        safe_stem = re.sub(r"\W", "_", path.stem)
        path_digest = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:16]
        module_name = f"skillsaw_custom_{safe_stem}_{path_digest}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, path)
            module = importlib.util.module_from_spec(spec)
            # Register before exec (the documented module_from_spec pattern) so
            # the module is importable by name and rule classes carry a distinct
            # __module__ — this is what keeps two rule files from colliding.
            sys.modules[module_name] = module
            try:
                spec.loader.exec_module(module)
            except Exception:
                sys.modules.pop(module_name, None)
                raise
        except Exception as e:
            # Surface a friendly error (the CLI catches ValueError) instead of
            # leaking a SyntaxError/ImportError traceback from the rule file.
            raise ValueError(f"Failed to load custom rule from {path}: {e}") from e

        try:
            for name in dir(module):
                obj = getattr(module, name)
                if isinstance(obj, type) and issubclass(obj, Rule) and obj is not Rule:
                    rule_instance = obj()
                    self._known_rule_ids.add(rule_instance.rule_id)
                    if self._rule_ids and rule_instance.rule_id not in self._rule_ids:
                        continue
                    if rule_instance.rule_id in self._skip_rule_ids:
                        logger.info(
                            "Rule %-30s skipped (--skip-rule, custom: %s)",
                            rule_instance.rule_id,
                            path.name,
                        )
                        continue
                    config = self.config.get_rule_config(rule_instance.rule_id)
                    if config:
                        rule_instance = obj(config)

                    if self._rule_ids or self.config.is_rule_enabled(
                        rule_instance.rule_id,
                        self.context,
                        rule_instance.repo_types,
                        rule_instance.formats,
                        since_version=rule_instance.since,
                    ):
                        rule_instance._source = "custom"
                        self.rules.append(rule_instance)
                        logger.info(
                            "Rule %-30s enabled (custom: %s)",
                            rule_instance.rule_id,
                            path.name,
                        )
                    else:
                        logger.info(
                            "Rule %-30s skipped (custom: %s)",
                            rule_instance.rule_id,
                            path.name,
                        )
        except Exception as e:
            raise ValueError(f"Failed to load custom rule from {path}: {e}") from e

    def _validate_config(self) -> List[RuleViolation]:
        """Check for unknown rule IDs in config"""
        # With --no-custom-rules, IDs supplied by unloaded custom rule files
        # are unknowable without executing them — exactly what the flag
        # forbids. Don't flag config entries as typos in that case.
        skip_unknown = self._no_custom_rules and bool(self.config.custom_rules)
        warnings = []
        for rule_id in self.config.rules:
            if rule_id not in self._known_rule_ids:
                if skip_unknown:
                    logger.info(
                        "Rule %-30s unknown in config; may be a custom rule "
                        "(skipped due to --no-custom-rules)",
                        rule_id,
                    )
                    continue
                warnings.append(
                    RuleViolation(
                        rule_id="invalid-config",
                        severity=Severity.WARNING,
                        message=f"Unknown rule '{rule_id}' in config — rule does not exist and will be ignored",
                    )
                )
        return warnings

    def _is_excluded(self, violation: RuleViolation) -> bool:
        """Check if a violation's file path matches any exclude pattern."""
        if violation.file_path is None:
            return False
        return self.context.is_path_excluded(violation.file_path)

    def _is_rule_excluded(self, rule_id: str, file_path: Optional[Path]) -> bool:
        """Check if a file path matches a rule's per-rule excludes patterns."""
        if file_path is None:
            return False
        exclude = self.config.get_rule_config(rule_id).get("exclude")
        if not exclude:
            return False
        from .context import path_matches_patterns

        return path_matches_patterns(file_path, self.context.root_path, exclude)

    def _get_suppression_map(self, file_path: Path) -> Optional[SuppressionMap]:
        """Get or build a suppression map for a file, with caching."""
        resolved = file_path.resolve()
        if not hasattr(self, "_suppression_cache"):
            self._suppression_cache: Dict[Path, Optional[SuppressionMap]] = {}
        if resolved not in self._suppression_cache:
            self._suppression_cache[resolved] = build_suppression_map_for_file(resolved)
        return self._suppression_cache[resolved]

    def _is_inline_suppressed(self, violation: RuleViolation) -> bool:
        """Check if a violation is suppressed by an inline directive."""
        if violation.file_path is None:
            return False
        file_line = violation.file_line
        if file_line is None:
            return False
        smap = self._get_suppression_map(violation.file_path)
        if smap is None:
            return False
        return smap.is_suppressed(violation.rule_id, file_line)

    def _filter_violations(
        self, violations: List[RuleViolation], record_baseline: bool = True
    ) -> List[RuleViolation]:
        """Filter violations by global excludes, per-rule excludes, and inline suppression.

        When *record_baseline* is False, baseline subtraction still applies
        but stale/suppressed accounting is left untouched — used for the
        per-rule calls in :meth:`fix`, which would otherwise overwrite the
        accounting with only the last rule's view of the baseline.
        """
        kept: List[RuleViolation] = []
        for v in violations:
            if self._is_excluded(v):
                logger.info(
                    "Suppressed %-30s %s (global exclude)",
                    v.rule_id,
                    v.file_path or "(no file)",
                )
            elif self._is_rule_excluded(v.rule_id, v.file_path):
                logger.info(
                    "Suppressed %-30s %s (per-rule exclude)",
                    v.rule_id,
                    v.file_path or "(no file)",
                )
            elif self._is_inline_suppressed(v):
                logger.info(
                    "Suppressed %-30s %s:%s (inline directive)",
                    v.rule_id,
                    v.file_path or "(no file)",
                    v.file_line or "?",
                )
            else:
                kept.append(v)
        if len(kept) < len(violations):
            logger.info(
                "Filtered %d of %d violations via excludes/suppression",
                len(violations) - len(kept),
                len(violations),
            )

        if self._baseline is not None:
            from .baseline import filter_baselined_violations

            before = len(kept)
            baseline_root = self._baseline.root_path or self.context.root_path
            kept, stale = filter_baselined_violations(kept, self._baseline, baseline_root)
            if record_baseline:
                self._stale_baseline_entries = stale
                self._baseline_suppressed_count = before - len(kept)
            if before > len(kept):
                logger.info(
                    "Filtered %d of %d violations via baseline",
                    before - len(kept),
                    before,
                )
            if stale:
                logger.info(
                    "Baseline: %d stale entries (violations no longer present)",
                    len(stale),
                )

        return kept

    @property
    def stale_baseline_entries(self) -> List["BaselineEntry"]:
        return self._stale_baseline_entries

    @property
    def baseline_suppressed_count(self) -> int:
        return self._baseline_suppressed_count

    def run(
        self, progress: Optional[Callable[[int, int, str], None]] = None
    ) -> List[RuleViolation]:
        """
        Run all enabled rules

        Args:
            progress: Optional callback invoked before each rule check with
                ``(rule_number, total_rules, rule_id)`` — used by the CLI to
                show interactive progress on long lints.

        Returns:
            List of all violations found
        """
        violations = self._validate_config()

        logger.info("Running %d enabled rules", len(self.rules))
        total = len(self.rules)
        for index, rule in enumerate(self.rules, 1):
            if progress is not None:
                progress(index, total, rule.rule_id)
            try:
                rule_violations = rule.check(self.context)
                if rule_violations:
                    logger.info(
                        "Rule %-30s found %d violation(s)", rule.rule_id, len(rule_violations)
                    )
                violations.extend(rule_violations)
            except Exception as e:
                print(f"Error running rule {rule.rule_id}: {e}", file=sys.stderr)
                violations.append(self._crash_violation(rule, e))

        return self._filter_violations(violations)

    @staticmethod
    def _crash_violation(rule: Rule, exc: Exception, action: str = "check") -> RuleViolation:
        """Surface a rule crash as an ERROR violation so it affects the exit code."""
        return RuleViolation(
            rule_id="rule-execution-error",
            severity=Severity.ERROR,
            message=(
                f"Rule '{rule.rule_id}' crashed during {action}:"
                f" {exc.__class__.__name__}: {exc}"
            ),
        )

    def fix(
        self, progress: Optional[Callable[[int, int, str], None]] = None
    ) -> tuple[List[RuleViolation], List[AutofixResult]]:
        """
        Run all enabled rules and attempt to fix violations.

        Args:
            progress: Optional callback invoked before each rule check with
                ``(rule_number, total_rules, rule_id)``.

        Returns:
            Tuple of (remaining violations, autofix results)
        """
        all_violations = self._validate_config()
        all_fixes: List[AutofixResult] = []
        checked: List[RuleViolation] = list(all_violations)

        total = len(self.rules)
        for index, rule in enumerate(self.rules, 1):
            if progress is not None:
                progress(index, total, rule.rule_id)
            try:
                rule_violations = rule.check(self.context)
            except Exception as e:
                print(f"Error running rule {rule.rule_id}: {e}", file=sys.stderr)
                all_violations.append(self._crash_violation(rule, e))
                continue

            checked.extend(rule_violations)
            visible = self._filter_violations(rule_violations, record_baseline=False)

            if visible and rule.supports_autofix:
                try:
                    fixes = rule.fix(self.context, visible)
                    all_fixes.extend(fixes)
                    fixed_violations = {id(v) for fix in fixes for v in fix.violations_fixed}
                    remaining = [v for v in visible if id(v) not in fixed_violations]
                    all_violations.extend(remaining)
                except Exception as e:
                    print(f"Error fixing rule {rule.rule_id}: {e}", file=sys.stderr)
                    all_violations.append(self._crash_violation(rule, e, action="fix"))
                    all_violations.extend(visible)
            else:
                all_violations.extend(visible)

        # Baseline stale/suppressed accounting must consider all rules'
        # violations together, exactly as run() does — the per-rule calls
        # above skip it (record_baseline=False).
        if self._baseline is not None:
            self._filter_violations(checked)

        return all_violations, all_fixes

    @staticmethod
    def _first_per_file(
        fixes: List[AutofixResult],
    ) -> tuple[List[AutofixResult], bool]:
        """Snapshot-isolation filter: first-committer-wins per file.

        Returns the independent subset (at most one fix per file) and
        whether any fixes were deferred due to file-level conflicts.
        Deferred fixes are not applied — the next pass will re-derive
        them against the committed file state.
        """
        seen: set[Path] = set()
        independent: List[AutofixResult] = []
        has_conflicts = False
        for fix in fixes:
            targets = {fix.file_path.resolve()}
            if fix.rename_from is not None:
                targets.add(fix.rename_from.resolve())
            if any(t in seen for t in targets):
                has_conflicts = True
            else:
                seen.update(targets)
                independent.append(fix)
        return independent, has_conflicts

    def fix_and_apply(
        self,
        confidence: AutofixConfidence = AutofixConfidence.SAFE,
        max_passes: int = 10,
        dry_run: bool = False,
        progress: Optional[Callable[[int, int, str], None]] = None,
    ) -> tuple[List[AutofixResult], List[AutofixResult]]:
        """Fixed-point iteration over autofix passes with snapshot isolation.

        Each fix is a pre-computed transformation against a file snapshot.
        When two fixes target the same file, the second holds a stale
        snapshot — a classic write-write conflict.

        This method resolves conflicts via first-committer-wins: each pass
        applies at most one fix per file (the independent set of the
        conflict graph).  Conflicting fixes are never applied with stale
        data — they are discarded and re-derived on the next pass against
        the committed file state.

        Converges when a pass produces no file-level conflicts, or when
        no new fixes are found (the fixed point).

        Args:
            confidence: Minimum confidence level to apply.
            max_passes: Safety cap on iterations.

        Returns:
            Tuple of (applied fixes, suggested-but-not-applied fixes).
        """
        from .rules.builtin.utils import invalidate_read_caches

        all_applied: List[AutofixResult] = []
        all_suggested: List[AutofixResult] = []

        allowed = {AutofixConfidence.SAFE}
        if confidence == AutofixConfidence.SUGGEST:
            allowed.add(AutofixConfidence.SUGGEST)

        for _ in range(max_passes):
            _violations, fixes = self.fix(progress=progress)
            if not fixes:
                break

            applicable = [f for f in fixes if f.confidence in allowed]
            suggested = [f for f in fixes if f.confidence not in allowed]
            all_suggested.extend(suggested)

            if not applicable:
                break

            independent, has_conflicts = self._first_per_file(applicable)

            if dry_run:
                all_applied.extend(independent)
                break

            applied = self.apply_fixes(independent, confidence)
            all_applied.extend(applied)

            # An on_apply side effect (e.g. recording a rename in the
            # manifest) can unlock new violations for other rules, so a
            # further pass is needed even without file-level conflicts.
            state_changed = any(f.on_apply is not None for f in applied)
            if not applied or not (has_conflicts or state_changed):
                break

            invalidate_read_caches()
            self.context.rebuild_lint_tree()
            if hasattr(self, "_suppression_cache"):
                self._suppression_cache.clear()

        return all_applied, all_suggested

    @staticmethod
    def apply_fixes(
        fixes: List[AutofixResult],
        confidence: AutofixConfidence = AutofixConfidence.SAFE,
    ) -> List[AutofixResult]:
        """
        Write fix results to disk.

        Args:
            fixes: Autofix results to apply
            confidence: Minimum confidence level to apply
                        (SAFE = only safe,
                         SUGGEST = safe + suggest)

        Returns:
            List of fixes that were actually applied
        """
        applied: List[AutofixResult] = []
        allowed = {AutofixConfidence.SAFE}
        if confidence == AutofixConfidence.SUGGEST:
            allowed.add(AutofixConfidence.SUGGEST)

        for fix in fixes:
            if fix.confidence not in allowed:
                continue

            try:
                if fix.rename_from is not None:
                    # Rename operation: use Path.rename() for atomicity and
                    # safety on case-insensitive filesystems (macOS/Windows).
                    # If the source no longer exists or the target already exists
                    # (and isn't the same file on a case-insensitive FS), skip.
                    src = fix.rename_from
                    dst = fix.file_path
                    if not src.exists():
                        continue
                    # On case-insensitive filesystems src and dst may resolve to
                    # the same inode even when their names differ in casing.
                    # Path.rename() handles this correctly, but we must not skip
                    # a case-only rename via the ``dst.exists()`` guard.
                    same_file = src.resolve() == dst.resolve()
                    if dst.exists() and not same_file:
                        continue
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    src.rename(dst)
                    # If the content also changed, write the updated content
                    if fix.fixed_content != fix.original_content:
                        dst.write_text(fix.fixed_content, encoding="utf-8")
                else:
                    fix.file_path.write_text(fix.fixed_content, encoding="utf-8")
            except OSError as exc:
                logger.warning(
                    "Failed to apply fix for %s on %s: %s",
                    fix.rule_id,
                    fix.file_path,
                    exc,
                )
                continue

            if fix.on_apply is not None:
                try:
                    fix.on_apply()
                except OSError as exc:
                    logger.warning(
                        "on_apply side effect failed for %s on %s: %s",
                        fix.rule_id,
                        fix.file_path,
                        exc,
                    )

            applied.append(fix)

        return applied

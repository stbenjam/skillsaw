"""
Main linter orchestration
"""

from __future__ import annotations

import fnmatch
import importlib.util
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, TYPE_CHECKING

logger = logging.getLogger(__name__)

from .rule import Rule, RuleViolation, Severity, AutofixResult, AutofixConfidence
from .context import RepositoryContext
from .config import LinterConfig
from .suppression import build_suppression_map_for_file, SuppressionMap

if TYPE_CHECKING:
    from .llm._litellm import CompletionProvider, TokenUsage


@dataclass
class LLMFixResult:
    files_modified: List[Path]
    violations_before: int
    violations_after: int
    total_usage: "TokenUsage"
    diffs: Dict[Path, str]
    success: bool

    @property
    def violations_fixed(self) -> int:
        return max(0, self.violations_before - self.violations_after)


class Linter:
    """
    Main linter that orchestrates rule checking
    """

    def __init__(
        self,
        context: RepositoryContext,
        config: LinterConfig = None,
        rule_ids: Optional[Set[str]] = None,
    ):
        """
        Initialize linter

        Args:
            context: Repository context
            config: Linter configuration (uses default if None)
            rule_ids: If set, only load rules with these IDs
        """
        self.context = context
        self.config = config or LinterConfig.default()
        self._rule_ids = rule_ids
        self.context.content_paths = self.config.content_paths
        self.context.exclude_patterns = self.config.exclude_patterns
        self.context.apply_excludes()
        self.rules: List[Rule] = []
        self._load_rules()

    def _load_rules(self):
        """Load all enabled rules"""
        self._known_rule_ids: set = set()

        # Load builtin rules
        self._load_builtin_rules()

        # Load custom rules
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
            path = self.context.root_path / path
        path = path.resolve()

        if not path.exists():
            raise FileNotFoundError(f"Custom rule file not found: {path}")

        logger.info("Loading custom rules from %s", path)

        spec = importlib.util.spec_from_file_location("custom_rule", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        for name in dir(module):
            obj = getattr(module, name)
            if isinstance(obj, type) and issubclass(obj, Rule) and obj is not Rule:
                rule_instance = obj()
                self._known_rule_ids.add(rule_instance.rule_id)
                if self._rule_ids and rule_instance.rule_id not in self._rule_ids:
                    continue
                config = self.config.get_rule_config(rule_instance.rule_id)
                if config:
                    rule_instance = obj(config)

                if self._rule_ids or self.config.is_rule_enabled(
                    rule_instance.rule_id,
                    self.context,
                    rule_instance.repo_types,
                    rule_instance.formats,
                ):
                    self.rules.append(rule_instance)
                    logger.info("Rule %-30s enabled (custom: %s)", rule_instance.rule_id, path.name)
                else:
                    logger.info("Rule %-30s skipped (custom: %s)", rule_instance.rule_id, path.name)

    def _validate_config(self) -> List[RuleViolation]:
        """Check for unknown rule IDs in config"""
        warnings = []
        for rule_id in self.config.rules:
            if rule_id not in self._known_rule_ids:
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
        rule_config = self.config.get_rule_config(rule_id)
        exclude = rule_config.get("exclude")
        if not exclude:
            return False
        try:
            rel = str(file_path.resolve().relative_to(self.context.root_path))
        except ValueError:
            return False
        return any(fnmatch.fnmatch(rel, pat) for pat in exclude)

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

    def _filter_violations(self, violations: List[RuleViolation]) -> List[RuleViolation]:
        """Filter violations by global excludes, per-rule excludes, and inline suppression."""
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
        return kept

    def run(self) -> List[RuleViolation]:
        """
        Run all enabled rules

        Returns:
            List of all violations found
        """
        violations = self._validate_config()

        logger.info("Running %d enabled rules", len(self.rules))
        for rule in self.rules:
            try:
                rule_violations = rule.check(self.context)
                if rule_violations:
                    logger.info(
                        "Rule %-30s found %d violation(s)", rule.rule_id, len(rule_violations)
                    )
                violations.extend(rule_violations)
            except Exception as e:
                print(f"Error running rule {rule.rule_id}: {e}", file=sys.stderr)

        return self._filter_violations(violations)

    def fix(self) -> tuple[List[RuleViolation], List[AutofixResult]]:
        """
        Run all enabled rules and attempt to fix violations.

        Returns:
            Tuple of (remaining violations, autofix results)
        """
        all_violations = self._validate_config()
        all_fixes: List[AutofixResult] = []

        for rule in self.rules:
            try:
                rule_violations = rule.check(self.context)
            except Exception as e:
                print(f"Error running rule {rule.rule_id}: {e}", file=sys.stderr)
                continue

            visible = self._filter_violations(rule_violations)

            if visible and rule.supports_autofix:
                try:
                    fixes = rule.fix(self.context, visible)
                    all_fixes.extend(fixes)
                    fixed_violations = {id(v) for fix in fixes for v in fix.violations_fixed}
                    remaining = [v for v in visible if id(v) not in fixed_violations]
                    all_violations.extend(remaining)
                except Exception as e:
                    print(f"Error fixing rule {rule.rule_id}: {e}", file=sys.stderr)
                    all_violations.extend(visible)
            else:
                all_violations.extend(visible)

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
        elif confidence == AutofixConfidence.LLM:
            allowed.update({AutofixConfidence.SUGGEST, AutofixConfidence.LLM})

        for _ in range(max_passes):
            _violations, fixes = self.fix()
            if not fixes:
                break

            applicable = [f for f in fixes if f.confidence in allowed]
            suggested = [f for f in fixes if f.confidence not in allowed]
            all_suggested.extend(suggested)

            if not applicable:
                break

            independent, has_conflicts = self._first_per_file(applicable)

            applied = self.apply_fixes(independent, confidence)
            all_applied.extend(applied)

            if not applied or not has_conflicts:
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
                         SUGGEST = safe + suggest,
                         LLM = safe + suggest + llm)

        Returns:
            List of fixes that were actually applied
        """
        applied: List[AutofixResult] = []
        allowed = {AutofixConfidence.SAFE}
        if confidence == AutofixConfidence.SUGGEST:
            allowed.add(AutofixConfidence.SUGGEST)
        elif confidence == AutofixConfidence.LLM:
            allowed.update({AutofixConfidence.SUGGEST, AutofixConfidence.LLM})

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

            applied.append(fix)

        return applied

    _SEVERITY_ORDER = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}

    @staticmethod
    def _build_llm_system_prompt(rel_path, violations_list, llm_rules):
        prompts = set()
        for v in violations_list:
            prompt = llm_rules[v.rule_id].llm_fix_prompt
            if prompt:
                prompts.add(prompt)
        formatted = "\n".join(str(v) for v in violations_list)
        combined = "\n\n".join(prompts)
        return (
            f"You are fixing lint violations in: {rel_path}\n\n"
            f"VIOLATIONS TO FIX:\n{formatted}\n\n"
            f"RULE GUIDANCE:\n{combined}\n\n"
            "TOOLS:\n"
            "- read_file(path) — read a file\n"
            "- write_file(path, content) — overwrite entire file\n"
            "- replace_section(path, old_text, new_text) — surgical edit "
            "(old_text must match exactly)\n"
            "- lint(path) — re-run the linter to check your work\n"
            "- diff(path) — see changes vs original\n\n"
            "INSTRUCTIONS:\n"
            "1. read_file to see current content\n"
            "2. Fix each violation using replace_section (prefer small, "
            "targeted edits over rewriting the whole file)\n"
            "3. After all edits, call lint() to verify — if violations "
            "remain, fix them and lint again\n"
            "4. When done, call diff() then respond with a brief summary\n\n"
            "IMPORTANT:\n"
            "- Do not change anything unrelated to the violations\n"
            "- Preserve the file's structure, formatting, and meaning\n"
            "- Only modify the specific text that triggers each violation\n"
            "- NEVER call lint() unless you have made changes since "
            "the last lint — re-linting unchanged code wastes iterations\n"
            "- If lint still shows violations after your edits, make a "
            "different edit before linting again"
        )

    @staticmethod
    def _build_block_system_prompt(block, violations_list, llm_rules, *, body_context=None):
        prompts = set()
        for v in violations_list:
            prompt = llm_rules[v.rule_id].llm_fix_prompt
            if prompt:
                prompts.add(prompt)
        formatted = "\n".join(str(v) for v in violations_list)
        combined = "\n\n".join(prompts)

        body_section = ""
        if body_context:
            body_section = (
                f"\nFILE BODY (read-only context — do NOT include this in your edits):\n"
                f"{body_context}\n\n"
            )

        return (
            f"You are fixing lint violations in a content block from: "
            f"{block.path.name} ({block.category})\n\n"
            f"VIOLATIONS TO FIX:\n{formatted}\n\n"
            f"RULE GUIDANCE:\n{combined}\n\n"
            f"{body_section}"
            "TOOLS:\n"
            "- read_block() — read the content block\n"
            "- replace_block_section(old_text, new_text) — surgical edit\n"
            "- write_block(content) — overwrite the entire block\n"
            "- lint_block() — re-run lint to check your work\n"
            "- diff_block() — see changes vs original\n"
            "- read_file(path) — read another file for context (read-only)\n\n"
            "INSTRUCTIONS:\n"
            "1. read_block() to see the content\n"
            "2. Fix each violation using replace_block_section\n"
            "3. After all edits, call lint_block() to verify\n"
            "4. When done, call diff_block() then respond with a brief summary\n\n"
            "IMPORTANT:\n"
            "- Only modify text that triggers violations\n"
            "- Preserve meaning and structure\n"
            "- NEVER call lint_block() without making changes first"
        )

    def _relint_file(self, fpath, violations_list, threshold, *, block=None):
        from .rules.builtin.utils import invalidate_read_caches

        invalidate_read_caches(fpath)
        context = RepositoryContext(self.context.root_path)
        context.content_paths = self.config.content_paths
        context.exclude_patterns = self.config.exclude_patterns
        context.apply_excludes()

        failed_rule_ids = {v.rule_id for v in violations_list}
        failed_rules = [r for r in self.rules if r.rule_id in failed_rule_ids]
        remaining = []
        for rule in failed_rules:
            try:
                re_violations = rule.check(context)
                for v in re_violations:
                    if self._SEVERITY_ORDER.get(v.severity, 99) > threshold:
                        continue
                    if block is not None:
                        if v.block == block:
                            remaining.append(v)
                    elif v.file_path and v.file_path.resolve() == fpath:
                        remaining.append(v)
            except Exception as e:
                logger.warning("Rule %s failed during re-lint of %s: %s", rule.rule_id, fpath, e)
                remaining.extend(v for v in violations_list if v.rule_id == rule.rule_id)
        return remaining

    def _llm_process_one_file(
        self,
        file_idx,
        fpath,
        file_violations,
        *,
        provider,
        llm_rules,
        originals,
        file_count,
        root_resolved,
        base_max_iter,
        threshold,
        emit,
    ):
        from .llm.tools import ReadFileTool, WriteFileTool, ReplaceSectionTool, LintTool, DiffTool
        from .llm.engine import LLMEngine
        from .llm._litellm import TokenUsage
        import difflib

        file_usage = TokenUsage(0, 0)
        file_max_iter = max(base_max_iter, len(file_violations) * 5)
        rel_path = fpath.relative_to(root_resolved)

        rules_for_file = sorted({v.rule_id for v in file_violations})
        emit(
            "file_start",
            file_idx=file_idx,
            file_count=file_count,
            rel_path=rel_path,
            num_violations=len(file_violations),
            rule_ids=rules_for_file,
        )

        def _on_engine_event(event_type, **kwargs):
            emit(
                event_type,
                file_idx=file_idx,
                file_count=file_count,
                rel_path=rel_path,
                **kwargs,
            )

        tools = [
            ReadFileTool(self.context.root_path),
            WriteFileTool(self.context.root_path),
            ReplaceSectionTool(self.context.root_path),
            LintTool(
                self.context.root_path,
                self.config,
                rule_ids={v.rule_id for v in file_violations},
            ),
            DiffTool(self.context.root_path, originals),
        ]

        current_violations = file_violations
        total_iterations = 0
        remaining = []
        for attempt in range(2):
            engine = LLMEngine(
                provider,
                tools,
                model=self.config.llm.model,
                max_iterations=file_max_iter,
                max_tokens=self.config.llm.max_tokens,
                on_event=_on_engine_event,
            )
            result = engine.run(
                system_prompt=self._build_llm_system_prompt(
                    rel_path, current_violations, llm_rules
                ),
                user_message=f"Please fix the violations in {rel_path}.",
            )
            file_usage.prompt_tokens += result.usage.prompt_tokens
            file_usage.completion_tokens += result.usage.completion_tokens
            total_iterations += result.iterations

            remaining = self._relint_file(fpath, current_violations, threshold)
            if not remaining:
                break

            if attempt == 0:
                emit(
                    "retry",
                    file_idx=file_idx,
                    file_count=file_count,
                    rel_path=rel_path,
                    remaining=len(remaining),
                )
                current_violations = remaining

        changed = False
        diff_text = None
        if fpath.exists() and fpath in originals:
            current = fpath.read_text(encoding="utf-8")
            original = originals[fpath]
            if original is None:
                # File was created by the LLM (didn't exist before)
                diff_lines = difflib.unified_diff(
                    [],
                    current.splitlines(keepends=True),
                    fromfile=f"a/{rel_path}",
                    tofile=f"b/{rel_path}",
                )
                diff_text = "".join(diff_lines)
                if diff_text:
                    changed = True
            elif current != original:
                diff_lines = difflib.unified_diff(
                    original.splitlines(keepends=True),
                    current.splitlines(keepends=True),
                    fromfile=f"a/{rel_path}",
                    tofile=f"b/{rel_path}",
                )
                diff_text = "".join(diff_lines)
                if diff_text:
                    changed = True

        emit(
            "file_done",
            file_idx=file_idx,
            file_count=file_count,
            rel_path=rel_path,
            num_violations=len(file_violations),
            iterations=total_iterations,
            remaining=len(remaining),
            changed=changed,
        )

        return {
            "fpath": fpath,
            "usage": file_usage,
            "diff_text": diff_text,
            "changed": changed,
        }

    def _llm_process_one_block(
        self,
        block_idx,
        block,
        block_violations,
        *,
        provider,
        llm_rules,
        block_count,
        root_resolved,
        base_max_iter,
        threshold,
        emit,
    ):
        from .llm.tools import (
            ReadFileTool,
            BlockState,
            ReadBlockTool,
            WriteBlockTool,
            ReplaceBlockSectionTool,
            LintBlockTool,
            DiffBlockTool,
        )
        from .llm.engine import LLMEngine
        from .llm._litellm import TokenUsage
        import difflib

        block_usage = TokenUsage(0, 0)
        block_max_iter = max(base_max_iter, len(block_violations) * 5)
        rel_path = block.path.relative_to(root_resolved)

        rules_for_block = sorted({v.rule_id for v in block_violations})
        emit(
            "file_start",
            file_idx=block_idx,
            file_count=block_count,
            rel_path=rel_path,
            num_violations=len(block_violations),
            rule_ids=rules_for_block,
        )

        def _on_engine_event(event_type, **kwargs):
            emit(
                event_type,
                file_idx=block_idx,
                file_count=block_count,
                rel_path=rel_path,
                **kwargs,
            )

        fm_mode = any(llm_rules[v.rule_id].llm_fix_frontmatter for v in block_violations)
        state = BlockState(block, frontmatter_mode=fm_mode)
        original_body = state.original
        tools = [
            ReadBlockTool(state),
            WriteBlockTool(state),
            ReplaceBlockSectionTool(state),
            LintBlockTool(
                state,
                self.config,
                root=self.context.root_path,
                rule_ids={v.rule_id for v in block_violations},
            ),
            DiffBlockTool(state),
            ReadFileTool(self.context.root_path),
        ]

        current_violations = block_violations
        total_iterations = 0
        remaining = []
        for attempt in range(2):
            engine = LLMEngine(
                provider,
                tools,
                model=self.config.llm.model,
                max_iterations=block_max_iter,
                max_tokens=self.config.llm.max_tokens,
                on_event=_on_engine_event,
            )
            result = engine.run(
                system_prompt=self._build_block_system_prompt(
                    block,
                    current_violations,
                    llm_rules,
                    body_context=state.body_context,
                ),
                user_message="Please fix the violations in this content block.",
            )
            block_usage.prompt_tokens += result.usage.prompt_tokens
            block_usage.completion_tokens += result.usage.completion_tokens
            total_iterations += result.iterations

            remaining = self._relint_file(
                block.path.resolve(), current_violations, threshold, block=block
            )
            if not remaining:
                break

            if attempt == 0:
                emit(
                    "retry",
                    file_idx=block_idx,
                    file_count=block_count,
                    rel_path=rel_path,
                    remaining=len(remaining),
                )
                current_violations = remaining

        changed = state.body != original_body
        diff_text = None
        if changed:
            diff_lines = difflib.unified_diff(
                original_body.splitlines(keepends=True),
                state.body.splitlines(keepends=True),
                fromfile=f"a/{rel_path}",
                tofile=f"b/{rel_path}",
            )
            diff_text = "".join(diff_lines)

        emit(
            "file_done",
            file_idx=block_idx,
            file_count=block_count,
            rel_path=rel_path,
            num_violations=len(block_violations),
            iterations=total_iterations,
            remaining=len(remaining),
            changed=changed,
        )

        return {
            "block": block,
            "original_body": original_body,
            "usage": block_usage,
            "diff_text": diff_text,
            "changed": changed,
            "frontmatter_mode": fm_mode,
        }

    def _llm_rollback_or_keep(self, files_to_violations, originals, all_diffs, threshold):
        from .rules.builtin.utils import invalidate_read_caches

        invalidate_read_caches()
        violations_after = 0
        kept_files: List[Path] = []
        kept_diffs: Dict[Path, str] = {}

        for fpath, before_violations in files_to_violations.items():
            before_count = len(before_violations)
            if fpath not in originals or fpath not in all_diffs:
                violations_after += before_count
                continue

            after_count = sum(1 for v in self._relint_file(fpath, before_violations, threshold))

            if after_count >= before_count:
                original = originals[fpath]
                if original is None:
                    # File didn't exist before — remove the LLM-created file
                    if fpath.exists():
                        fpath.unlink()
                else:
                    fpath.write_text(original, encoding="utf-8")
                violations_after += before_count
            else:
                violations_after += after_count
                kept_files.append(fpath)
                kept_diffs[fpath] = all_diffs[fpath]

        return violations_after, kept_files, kept_diffs

    def llm_fix(
        self,
        provider: "CompletionProvider",
        callback: Optional[Callable[..., None]] = None,
        min_severity: Severity = Severity.WARNING,
        max_workers: int = 4,
        dry_run: bool = False,
    ) -> "LLMFixResult":
        from .llm._litellm import TokenUsage
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import threading

        threshold = self._SEVERITY_ORDER[min_severity]
        violations = self.run()
        llm_rules = {r.rule_id: r for r in self.rules if r.llm_fix_prompt is not None}
        llm_violations = [
            v
            for v in violations
            if v.rule_id in llm_rules and self._SEVERITY_ORDER.get(v.severity, 99) <= threshold
        ]

        if not llm_violations:
            return LLMFixResult(
                files_modified=[],
                violations_before=0,
                violations_after=0,
                total_usage=TokenUsage(0, 0),
                diffs={},
                success=True,
            )

        # Group violations by block (all violations now have blocks via auto-wrap)
        block_violations: Dict[Any, List[RuleViolation]] = {}
        file_violations: Dict[Path, List[RuleViolation]] = {}

        for v in llm_violations:
            if v.block is not None:
                block_violations.setdefault(v.block, []).append(v)
            elif v.file_path:
                file_violations.setdefault(v.file_path.resolve(), []).append(v)

        originals: Dict[Path, Optional[str]] = {}
        for fpath in file_violations:
            if fpath.exists():
                originals[fpath] = fpath.read_text(encoding="utf-8")
            else:
                originals[fpath] = None

        violations_before = len(llm_violations)
        total_units = len(block_violations) + len(file_violations)
        root_resolved = self.context.root_path.resolve()

        _cb_lock = threading.Lock()

        def _emit(event_type, **kw):
            if callback:
                with _cb_lock:
                    callback(event_type, **kw)

        total_usage = TokenUsage(0, 0)
        all_diffs: Dict[Path, str] = {}
        files_modified: List[Path] = []
        completed = 0

        _emit("progress", completed=0, file_count=total_units)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_idx = {}
            unit_idx = 0

            for block, bv in block_violations.items():
                unit_idx += 1
                future = executor.submit(
                    self._llm_process_one_block,
                    unit_idx,
                    block,
                    bv,
                    provider=provider,
                    llm_rules=llm_rules,
                    block_count=total_units,
                    root_resolved=root_resolved,
                    base_max_iter=self.config.llm.max_iterations,
                    threshold=threshold,
                    emit=_emit,
                )
                future_to_idx[future] = unit_idx

            for fpath, fv in file_violations.items():
                unit_idx += 1
                future = executor.submit(
                    self._llm_process_one_file,
                    unit_idx,
                    fpath,
                    fv,
                    provider=provider,
                    llm_rules=llm_rules,
                    originals=originals,
                    file_count=total_units,
                    root_resolved=root_resolved,
                    base_max_iter=self.config.llm.max_iterations,
                    threshold=threshold,
                    emit=_emit,
                )
                future_to_idx[future] = unit_idx

            block_results: List[dict] = []

            for future in as_completed(future_to_idx):
                try:
                    result = future.result()
                except Exception as e:
                    completed += 1
                    logger.error("Error processing unit: %s", e)
                    _emit("progress", completed=completed, file_count=total_units)
                    continue

                completed += 1
                _emit("progress", completed=completed, file_count=total_units)

                total_usage.prompt_tokens += result["usage"].prompt_tokens
                total_usage.completion_tokens += result["usage"].completion_tokens

                if "block" in result:
                    block_results.append(result)
                elif result["diff_text"]:
                    fpath = result.get("fpath")
                    if fpath:
                        all_diffs[fpath] = result["diff_text"]
                        files_modified.append(fpath)

        # Rollback file-based fixes that didn't help
        violations_after = 0
        kept_files: List[Path] = []
        kept_diffs: Dict[Path, str] = {}

        if file_violations:
            va, kf, kd = self._llm_rollback_or_keep(
                file_violations,
                originals,
                all_diffs,
                threshold,
            )
            violations_after += va
            kept_files.extend(kf)
            kept_diffs.update(kd)

        # Handle block-based results: rollback if no improvement, track diffs
        for br in block_results:
            block = br["block"]
            original_body = br["original_body"]
            before_count = len(block_violations.get(block, []))
            if not br["changed"]:
                violations_after += before_count
                continue
            after_remaining = self._relint_file(
                block.path.resolve(),
                block_violations.get(block, []),
                threshold,
                block=block,
            )
            after_count = len(after_remaining)

            if after_count >= before_count:
                if br.get("frontmatter_mode"):
                    block.write_frontmatter_text(original_body)
                else:
                    block.write_body(original_body)
                violations_after += before_count
            else:
                violations_after += after_count
                fpath = block.path
                if br["diff_text"]:
                    kept_diffs[fpath] = br["diff_text"]
                    kept_files.append(fpath)

        # Dry-run: restore all originals
        if dry_run:
            for fpath, original_content in originals.items():
                if original_content is None:
                    if fpath.exists():
                        fpath.unlink()
                else:
                    fpath.write_text(original_content, encoding="utf-8")
            for br in block_results:
                if br["changed"]:
                    if not br["original_body"] and br["block"].path.exists():
                        br["block"].path.unlink()
                    elif br.get("frontmatter_mode"):
                        br["block"].write_frontmatter_text(br["original_body"])
                    else:
                        br["block"].write_body(br["original_body"])

        return LLMFixResult(
            files_modified=[] if dry_run else kept_files,
            violations_before=violations_before,
            violations_after=violations_after,
            total_usage=total_usage,
            diffs=kept_diffs,
            success=len(kept_files) > 0 or len(kept_diffs) > 0,
        )

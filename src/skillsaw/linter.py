"""
Main linter orchestration
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, TYPE_CHECKING

logger = logging.getLogger(__name__)

from .rule import Rule, RuleViolation, Severity, AutofixResult, AutofixConfidence
from .context import RepositoryContext
from .config import LinterConfig

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

    def __init__(self, context: RepositoryContext, config: LinterConfig = None):
        """
        Initialize linter

        Args:
            context: Repository context
            config: Linter configuration (uses default if None)
        """
        self.context = context
        self.config = config or LinterConfig.default()
        self.context.content_paths = self.config.content_paths
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
            # Instantiate to discover rule_id (a property, not accessible on the class)
            rule_instance = rule_class()
            self._known_rule_ids.add(rule_instance.rule_id)
            config = self.config.get_rule_config(rule_instance.rule_id)
            if config:
                rule_instance = rule_class(config)

            # Check if enabled for this context
            if self.config.is_rule_enabled(
                rule_instance.rule_id,
                self.context,
                rule_instance.repo_types,
                rule_instance.formats,
            ):
                self.rules.append(rule_instance)

    def _load_custom_rule(self, rule_path: str):
        """
        Load a custom rule from a Python file

        Args:
            rule_path: Path to Python file containing Rule subclass
        """
        path = Path(rule_path)
        # If relative path, resolve relative to repository root
        if not path.is_absolute():
            path = self.context.root_path / path
        path = path.resolve()

        if not path.exists():
            raise FileNotFoundError(f"Custom rule file not found: {path}")

        # Load the module
        spec = importlib.util.spec_from_file_location("custom_rule", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Find Rule subclasses in the module
        for name in dir(module):
            obj = getattr(module, name)
            if isinstance(obj, type) and issubclass(obj, Rule) and obj is not Rule:
                # Instantiate to discover rule_id (a property, not accessible on the class)
                rule_instance = obj()
                self._known_rule_ids.add(rule_instance.rule_id)
                config = self.config.get_rule_config(rule_instance.rule_id)
                if config:
                    rule_instance = obj(config)

                # Check if enabled
                if self.config.is_rule_enabled(
                    rule_instance.rule_id,
                    self.context,
                    rule_instance.repo_types,
                    rule_instance.formats,
                ):
                    self.rules.append(rule_instance)

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

    def run(self) -> List[RuleViolation]:
        """
        Run all enabled rules

        Returns:
            List of all violations found
        """
        violations = self._validate_config()

        for rule in self.rules:
            try:
                rule_violations = rule.check(self.context)
                violations.extend(rule_violations)
            except Exception as e:
                print(f"Error running rule {rule.rule_id}: {e}", file=sys.stderr)

        return violations

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

            if rule_violations and rule.supports_autofix:
                try:
                    fixes = rule.fix(self.context, rule_violations)
                    all_fixes.extend(fixes)
                    fixed_violations = {id(v) for fix in fixes for v in fix.violations_fixed}
                    remaining = [v for v in rule_violations if id(v) not in fixed_violations]
                    all_violations.extend(remaining)
                except Exception as e:
                    print(f"Error fixing rule {rule.rule_id}: {e}", file=sys.stderr)
                    all_violations.extend(rule_violations)
            else:
                all_violations.extend(rule_violations)

        return all_violations, all_fixes

    @staticmethod
    def apply_fixes(
        fixes: List[AutofixResult],
        confidence: AutofixConfidence = AutofixConfidence.SAFE,
    ) -> List[AutofixResult]:
        """
        Write fix results to disk.

        Args:
            fixes: Autofix results to apply
            confidence: Minimum confidence level to apply (SAFE = only safe,
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
            fix.file_path.write_text(fix.fixed_content, encoding="utf-8")
            applied.append(fix)

        return applied

    _SEVERITY_ORDER = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}

    def llm_fix(
        self,
        provider: "CompletionProvider",
        callback: Optional[Callable[..., None]] = None,
        min_severity: Severity = Severity.WARNING,
        max_workers: int = 4,
    ) -> "LLMFixResult":
        from .llm.tools import ReadFileTool, WriteFileTool, ReplaceSectionTool, LintTool, DiffTool
        from .llm.engine import LLMEngine
        from .llm.config import LLMConfig as EngineLLMConfig
        from .llm._litellm import TokenUsage
        from concurrent.futures import ThreadPoolExecutor, as_completed

        import difflib

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

        files_to_violations: Dict[Path, List[RuleViolation]] = {}
        for v in llm_violations:
            if v.file_path:
                key = v.file_path.resolve()
                files_to_violations.setdefault(key, []).append(v)

        originals: Dict[Path, str] = {}
        for fpath in files_to_violations:
            if fpath.exists():
                originals[fpath] = fpath.read_text(encoding="utf-8")

        violations_before = len(llm_violations)
        base_max_iter = self.config.llm.max_iterations
        file_count = len(files_to_violations)
        root_resolved = self.context.root_path.resolve()

        def _process_one_file(file_idx, fpath, file_violations):
            events = []
            file_usage = TokenUsage(0, 0)

            file_max_iter = max(base_max_iter, len(file_violations) * 5)
            engine_config = EngineLLMConfig(
                model=self.config.llm.model,
                max_tokens=4096,
                max_iterations=file_max_iter,
                max_total_tokens=self.config.llm.max_tokens,
            )
            rel_path = fpath.relative_to(root_resolved)

            rules_for_file = sorted({v.rule_id for v in file_violations})
            events.append(("file_start", {
                "file_idx": file_idx,
                "file_count": file_count,
                "rel_path": rel_path,
                "num_violations": len(file_violations),
                "rule_ids": rules_for_file,
            }))

            def _on_engine_event(event_type, **kwargs):
                events.append((event_type, {
                    "file_idx": file_idx,
                    "file_count": file_count,
                    "rel_path": rel_path,
                    **kwargs,
                }))

            def _build_system_prompt(violations_list):
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

            def _relint_file(violations_list):
                from .rules.builtin.utils import invalidate_read_caches

                invalidate_read_caches()
                failed_rule_ids = {v.rule_id for v in violations_list}
                failed_rules = [r for r in self.rules if r.rule_id in failed_rule_ids]
                remaining = []
                for rule in failed_rules:
                    try:
                        re_violations = rule.check(self.context)
                        remaining.extend(
                            v
                            for v in re_violations
                            if v.file_path
                            and v.file_path.resolve() == fpath
                            and self._SEVERITY_ORDER.get(v.severity, 99) <= threshold
                        )
                    except Exception:
                        pass
                return remaining

            tools = [
                ReadFileTool(self.context.root_path),
                WriteFileTool(self.context.root_path),
                ReplaceSectionTool(self.context.root_path),
                LintTool(self.context.root_path, self.config),
                DiffTool(self.context.root_path, originals),
            ]

            current_violations = file_violations
            total_iterations = 0
            remaining = []
            for attempt in range(2):
                engine = LLMEngine(provider, tools, engine_config, on_event=_on_engine_event)
                result = engine.run(
                    system_prompt=_build_system_prompt(current_violations),
                    user_message=f"Please fix the violations in {rel_path}.",
                )
                file_usage.prompt_tokens += result.usage.prompt_tokens
                file_usage.completion_tokens += result.usage.completion_tokens
                total_iterations += result.iterations

                remaining = _relint_file(current_violations)
                if not remaining:
                    break

                if attempt == 0 and remaining:
                    events.append(("retry", {
                        "file_idx": file_idx,
                        "file_count": file_count,
                        "rel_path": rel_path,
                        "remaining": len(remaining),
                    }))
                    current_violations = remaining

            changed = False
            diff_text = None
            if fpath.exists():
                current = fpath.read_text(encoding="utf-8")
                if fpath in originals and current != originals[fpath]:
                    diff_lines = difflib.unified_diff(
                        originals[fpath].splitlines(keepends=True),
                        current.splitlines(keepends=True),
                        fromfile=f"a/{rel_path}",
                        tofile=f"b/{rel_path}",
                    )
                    diff_text = "".join(diff_lines)
                    if diff_text:
                        changed = True

            events.append(("file_done", {
                "file_idx": file_idx,
                "file_count": file_count,
                "rel_path": rel_path,
                "num_violations": len(file_violations),
                "iterations": total_iterations,
                "remaining": len(remaining),
                "changed": changed,
            }))

            return {
                "fpath": fpath,
                "events": events,
                "usage": file_usage,
                "diff_text": diff_text,
                "changed": changed,
            }

        total_usage = TokenUsage(0, 0)
        all_diffs: Dict[Path, str] = {}
        files_modified: List[Path] = []
        completed = 0

        if callback:
            callback("progress", completed=0, file_count=file_count)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_idx = {}
            for file_idx, (fpath, fv) in enumerate(files_to_violations.items(), 1):
                future = executor.submit(_process_one_file, file_idx, fpath, fv)
                future_to_idx[future] = file_idx

            for future in as_completed(future_to_idx):
                try:
                    file_result = future.result()
                except Exception as e:
                    completed += 1
                    logger.error("Error processing file: %s", e)
                    if callback:
                        callback("progress", completed=completed, file_count=file_count)
                    continue

                completed += 1
                if callback:
                    callback("progress", completed=completed, file_count=file_count)

                for event_type, kw in file_result["events"]:
                    if callback:
                        callback(event_type, **kw)

                total_usage.prompt_tokens += file_result["usage"].prompt_tokens
                total_usage.completion_tokens += file_result["usage"].completion_tokens
                if file_result["diff_text"]:
                    all_diffs[file_result["fpath"]] = file_result["diff_text"]
                    files_modified.append(file_result["fpath"])

        from .rules.builtin.utils import invalidate_read_caches

        invalidate_read_caches()
        after_violations = self.run()
        after_llm = [
            v
            for v in after_violations
            if v.rule_id in llm_rules and self._SEVERITY_ORDER.get(v.severity, 99) <= threshold
        ]
        violations_after = len(after_llm)

        if violations_after >= violations_before:
            for fpath, original_content in originals.items():
                fpath.write_text(original_content, encoding="utf-8")
            return LLMFixResult(
                files_modified=[],
                violations_before=violations_before,
                violations_after=violations_before,
                total_usage=total_usage,
                diffs={},
                success=False,
            )

        return LLMFixResult(
            files_modified=files_modified,
            violations_before=violations_before,
            violations_after=violations_after,
            total_usage=total_usage,
            diffs=all_diffs,
            success=True,
        )

"""Content broken internal reference rule"""

import difflib
import os
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

from skillsaw.rule import AutofixConfidence, AutofixResult, Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.markdown_doc import file_span, splice
from skillsaw.rules.builtin.content_analysis import (
    gather_all_content_blocks,
)


class ContentBrokenInternalReferenceRule(Rule):
    """Detect markdown links pointing to nonexistent files"""

    autofix_confidence = AutofixConfidence.SUGGEST

    formats = None
    since = "0.9.0"
    repo_types = None

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
            for link in cf.markdown.links():
                target = link.href.strip()
                # Skip URLs, anchors, and mailto
                if not target or target.startswith(("http://", "https://", "#", "mailto:")):
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
                            f"Broken internal link: [{link.text}]({target}) — target is outside repository",
                            block=cf,
                            line=link.body_line,
                        )
                    )
                    continue
                if not resolved.exists():
                    suggestion = self._find_similar(root, cf.path.parent, target_path)
                    msg = f"Broken internal link: [{link.text}]({target}) — target does not exist"
                    if suggestion:
                        msg += f" (did you mean '{suggestion}'?)"
                    elif not link.has_dest_span:
                        msg += " (reference-style link — fix the definition manually)"
                    violations.append(self.violation(msg, block=cf, line=link.body_line))
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
            edits = []
            violations_fixed = []
            used_spans = set()
            for old_target, suggestion, v in replacements:
                if v.block is None or v.file_line is None:
                    continue
                # Preserve any anchor from the original target.
                anchor = "#" + old_target.split("#", 1)[1] if "#" in old_target else ""
                doc = v.block.markdown
                for link in doc.links():
                    if (
                        not link.has_dest_span
                        or link.file_line != v.file_line
                        or link.href.strip() != old_target
                    ):
                        continue
                    span = file_span(
                        doc,
                        content,
                        link.dest_file_line,
                        link.dest_body_line,
                        link.dest_col_start,
                        link.dest_col_end,
                    )
                    if span is None:
                        continue
                    key = (link.dest_file_line, span[0], span[1])
                    if key in used_spans:
                        continue
                    used_spans.add(key)
                    edits.append((link.dest_file_line, span[0], span[1], suggestion + anchor))
                    violations_fixed.append(v)
                    break
            fixed = splice(content, edits)
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

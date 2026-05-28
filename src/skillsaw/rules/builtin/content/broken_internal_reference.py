"""Content broken internal reference rule"""

import difflib
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

from skillsaw.rule import AutofixConfidence, AutofixResult, Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.content_analysis import (
    gather_all_content_blocks,
)


class ContentBrokenInternalReferenceRule(Rule):
    """Detect markdown links pointing to nonexistent files"""

    autofix_confidence = AutofixConfidence.SUGGEST
    formats = None
    since = "0.9.0"
    repo_types = None

    _LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
    _INLINE_CODE_RE = re.compile(r"(`+).+?\1", re.DOTALL)
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
            body = self._INLINE_CODE_RE.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), body)
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
            lines = content.splitlines(True)
            violations_fixed = []
            for old_target, suggestion, v in replacements:
                fl = v.file_line
                if fl is None:
                    continue
                idx = fl - 1
                if idx < 0 or idx >= len(lines):
                    continue
                old_frag = f"]({old_target})"
                new_frag = f"]({suggestion})"
                if old_frag in lines[idx]:
                    lines[idx] = lines[idx].replace(old_frag, new_frag, 1)
                    violations_fixed.append(v)
            fixed = "".join(lines)
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

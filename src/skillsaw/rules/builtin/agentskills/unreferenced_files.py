"""AgentSkill unreferenced bundled file detection rule.

Every file bundled in a skill directory should be reachable from SKILL.md.
An unreferenced file is dead weight in the skill package and a shadow-
functionality security smell: research on malicious skills found that most
hide their behavior in bundled files SKILL.md never mentions (OWASP Agentic
Skills Top 10, AST01).

Reference semantics
-------------------

A file counts as referenced when its path or filename is mentioned in
SKILL.md or, transitively, in any local markdown file that is itself
reachable from SKILL.md (SKILL.md -> references/a.md -> references/b.md).

"Mentioned" is deliberately broader than markdown links, because bundled
scripts are typically invoked inside fenced code blocks (``python
scripts/run.py``) rather than linked:

* **Markdown links** are resolved via the markdown-it AST
  (:meth:`MarkdownDoc.links`) relative to the file containing the link,
  including links whose target is a directory.
* **Everything else** — code spans, fenced code block contents, and plain
  prose — is covered by a boundary-aware substring scan of the raw file
  text for the file's skill-relative path, its path relative to the
  mentioning file, and its bare filename.  Scanning the raw text is a
  strict superset of the ``code_spans()`` / ``fences()`` /
  ``text_segments()`` accessor surfaces (and additionally covers YAML
  frontmatter), with no per-line markdown parsing.

**Bare filenames count.**  A mention of ``run.py`` anywhere marks
``scripts/run.py`` as referenced.  Skills routinely refer to bundled
scripts by name alone ("run helper.py from the scripts directory"), so
requiring full relative paths would flag heavily-referenced files (false
positives).  The cost is that a dead file sharing a name with a referenced
one goes undetected (false negative) — the right trade-off for a
warning-severity hygiene rule.

**Directory mentions cover their contents** (``directory_mention_covers``,
default true): when SKILL.md says "read the files in ``references/``",
every file under ``references/`` counts as referenced.  Prose/code
directory mentions require the trailing slash (so the English word
"references" is not a directory mention); links may target the bare
directory path.

Built-in exclusions (never flagged): SKILL.md itself, README.md,
CHANGELOG.md, LICENSE / LICENSE.*, NOTICE / NOTICE.*, everything under
evals/, and hidden files or directories.  The ``exclude`` config option
adds glob patterns on top of (not replacing) these defaults.

A skill-root README.md additionally counts as a reference root alongside
SKILL.md: it is standard human-facing documentation, so a bundled file
documented there is neither dead weight nor hidden from review.
"""

import fnmatch
import os
import re
from collections import deque
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.lint_target import SkillNode
from skillsaw.markdown_doc import MarkdownDoc
from skillsaw.blocks import ContentBlock
from skillsaw.utils import read_text

# A path mention must not be embedded in a longer word/path-like token:
# `scripts/run.py` must not match inside `myscripts/run.py` or
# `scripts/run.pyc`, while `./scripts/run.py`, "`scripts/run.py`", and
# sentence-final "scripts/run.py." all still match.
_MENTION_BEFORE = r"(?<![A-Za-z0-9_-])"
_FILE_AFTER = r"(?![A-Za-z0-9_-]|\.[A-Za-z0-9])"
# A directory mention (needle ends with "/") must not be followed by more
# path characters — "references/guide.md" is a file mention, not a mention
# of the whole references/ directory.  "references/*" or "references/`"
# still count.
_DIR_AFTER = r"(?![A-Za-z0-9_.-])"

_EXTERNAL_LINK_PREFIXES = ("http://", "https://", "#", "mailto:")


class AgentSkillUnreferencedFilesRule(Rule):
    """Detect bundled skill files that SKILL.md never references"""

    repo_types = {
        RepositoryType.AGENTSKILLS,
        RepositoryType.SINGLE_PLUGIN,
        RepositoryType.MARKETPLACE,
        RepositoryType.DOT_CLAUDE,
    }
    since = "0.15.0"

    config_schema = {
        "directory_mention_covers": {
            "type": "bool",
            "default": True,
            "description": (
                "Treat a mention of a directory (e.g. `references/`) as "
                "referencing every file under it"
            ),
        },
        "exclude": {
            "type": "list",
            "default": [],
            "description": (
                "Additional glob patterns (matched against skill-relative "
                "paths and bare file names) exempt from dead-file detection; "
                "extends the built-in exclusions (SKILL.md, README.md, "
                "CHANGELOG.md, LICENSE*, NOTICE*, evals/, hidden files)"
            ),
        },
    }

    @property
    def rule_id(self) -> str:
        return "agentskill-unreferenced-files"

    @property
    def description(self) -> str:
        return (
            "Every bundled skill file should be referenced from SKILL.md, directly or transitively"
        )

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        # Per-run regex cache: needles (paths/filenames) repeat across the
        # markdown sources of a skill and across skills sharing file names.
        self._pattern_cache: Dict[Tuple[str, str], re.Pattern] = {}
        directory_covers = self.config.get(
            "directory_mention_covers",
            self.config_schema["directory_mention_covers"]["default"],
        )
        exclude_patterns = list(self.config.get("exclude", []) or [])

        violations: List[RuleViolation] = []
        for skill_node in context.lint_tree.find(SkillNode):
            skill_path = skill_node.path
            skill_md = skill_path / "SKILL.md"
            if not skill_md.is_file():
                continue  # agentskill-valid owns this failure mode

            all_files = self._bundled_files(skill_path)
            if not all_files:
                continue

            roots = [skill_md]
            readme = skill_path / "README.md"
            if readme.is_file():
                roots.append(readme)
            referenced = self._reachable_files(
                skill_node, skill_path, roots, all_files, directory_covers
            )

            skill_resolved = skill_path.resolve()
            for file_path in all_files:
                if file_path in referenced:
                    continue
                rel = file_path.resolve().relative_to(skill_resolved).as_posix()
                if self._is_excluded(rel, file_path.name, exclude_patterns):
                    continue
                violations.append(
                    self.violation(
                        f"'{rel}' is never referenced from SKILL.md (directly or "
                        "transitively) — unreferenced files are dead weight and "
                        "can hide unreviewed behavior",
                        file_path=file_path,
                    )
                )

        return violations

    # -- discovery -----------------------------------------------------------

    @staticmethod
    def _bundled_files(skill_path: Path) -> List[Path]:
        """All non-hidden files under the skill, skipping nested skill dirs."""
        files: List[Path] = []
        try:
            for dirpath, dirnames, filenames in os.walk(skill_path):
                dirnames[:] = sorted(
                    d
                    for d in dirnames
                    if not d.startswith(".") and not (Path(dirpath) / d / "SKILL.md").is_file()
                )
                base = Path(dirpath)
                for name in sorted(filenames):
                    if name.startswith("."):
                        continue
                    files.append(base / name)
        except OSError:
            pass
        return files

    @staticmethod
    def _is_excluded(rel: str, name: str, extra_patterns: List[str]) -> bool:
        if rel == "SKILL.md":
            return True
        if name in ("README.md", "CHANGELOG.md"):
            return True
        if name in ("LICENSE", "NOTICE") or name.startswith(("LICENSE.", "NOTICE.")):
            return True
        if rel.startswith("evals/"):
            return True
        for pattern in extra_patterns:
            if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(name, pattern):
                return True
        return False

    # -- reachability --------------------------------------------------------

    def _reachable_files(
        self,
        skill_node: SkillNode,
        skill_path: Path,
        roots: List[Path],
        all_files: List[Path],
        directory_covers: bool,
    ) -> Set[Path]:
        """Files referenced from the roots, following referenced local markdown."""
        skill_resolved = skill_path.resolve()
        rel_of = {f: f.resolve().relative_to(skill_resolved).as_posix() for f in all_files}
        all_dirs = self._candidate_dirs(rel_of.values())
        block_by_path = {block.path.resolve(): block for block in skill_node.find(ContentBlock)}

        referenced: Set[Path] = set()
        covered_dirs: Set[str] = set()
        queue: deque = deque(roots)
        processed: Set[Path] = set()

        while queue:
            source = queue.popleft()
            resolved_source = source.resolve()
            if resolved_source in processed:
                continue
            processed.add(resolved_source)

            text = read_text(source)
            if text is None:
                continue
            block = block_by_path.get(resolved_source)
            doc = block.markdown if block is not None else MarkdownDoc(text)

            newly_referenced: List[Path] = []

            # Markdown links, resolved relative to the linking file.
            link_files, link_dirs = self._link_targets(doc, source.parent, skill_resolved)
            if directory_covers:
                covered_dirs.update(link_dirs)
            for candidate in all_files:
                if candidate in referenced:
                    continue
                if candidate.resolve() in link_files or self._text_mentions(
                    text, candidate, rel_of[candidate], source.parent, skill_resolved
                ):
                    referenced.add(candidate)
                    newly_referenced.append(candidate)

            # Directory mentions in prose/code cover their contents.
            if directory_covers:
                for rel_dir in all_dirs - covered_dirs:
                    if self._dir_mentioned(text, rel_dir, source.parent, skill_resolved):
                        covered_dirs.add(rel_dir)
                for candidate in all_files:
                    if candidate in referenced:
                        continue
                    rel = rel_of[candidate]
                    if any(rel.startswith(d + "/") for d in covered_dirs):
                        referenced.add(candidate)
                        newly_referenced.append(candidate)

            # Transitive traversal: referenced local markdown becomes a source.
            for candidate in newly_referenced:
                if candidate.suffix.lower() == ".md" and candidate.resolve() not in processed:
                    queue.append(candidate)

        return referenced

    @staticmethod
    def _candidate_dirs(rels: Iterable[str]) -> Set[str]:
        dirs: Set[str] = set()
        for rel in rels:
            parts = rel.split("/")[:-1]
            for i in range(1, len(parts) + 1):
                dirs.add("/".join(parts[:i]))
        return dirs

    @staticmethod
    def _link_targets(
        doc: MarkdownDoc, base_dir: Path, skill_resolved: Path
    ) -> Tuple[Set[Path], Set[str]]:
        """Resolve local link targets to (files, skill-relative directories)."""
        files: Set[Path] = set()
        dirs: Set[str] = set()
        for link in doc.links():
            target = link.href.strip()
            if not target or target.startswith(_EXTERNAL_LINK_PREFIXES):
                continue
            target = target.split("#")[0]
            if not target:
                continue
            try:
                resolved = (base_dir / target).resolve()
            except OSError:
                continue
            if not resolved.is_relative_to(skill_resolved) or resolved == skill_resolved:
                continue
            if resolved.is_dir():
                dirs.add(resolved.relative_to(skill_resolved).as_posix())
            elif resolved.is_file():
                files.add(resolved)
        return files, dirs

    def _text_mentions(
        self,
        text: str,
        candidate: Path,
        rel: str,
        source_dir: Path,
        skill_resolved: Path,
    ) -> bool:
        needles = {rel, candidate.name}
        source_rel = self._relative_needle(candidate, source_dir, skill_resolved)
        if source_rel:
            needles.add(source_rel)
        return any(
            needle in text and self._pattern(needle, _FILE_AFTER).search(text) for needle in needles
        )

    def _dir_mentioned(
        self, text: str, rel_dir: str, source_dir: Path, skill_resolved: Path
    ) -> bool:
        needles = {rel_dir + "/"}
        source_rel = self._relative_needle(skill_resolved / rel_dir, source_dir, skill_resolved)
        if source_rel:
            needles.add(source_rel + "/")
        return any(
            needle in text and self._pattern(needle, _DIR_AFTER).search(text) for needle in needles
        )

    @staticmethod
    def _relative_needle(target: Path, source_dir: Path, skill_resolved: Path) -> Optional[str]:
        """Path of *target* relative to the mentioning file's directory.

        Lets ``references/a.md`` reference ``references/img/x.png`` as
        ``img/x.png``.  Upward (``..``) paths are skipped — the skill-relative
        needle already matches inside them.
        """
        rel = Path(os.path.relpath(target, source_dir)).as_posix()
        if rel.startswith(".."):
            return None
        return rel

    def _pattern(self, needle: str, after: str) -> re.Pattern:
        key = (needle, after)
        pattern = self._pattern_cache.get(key)
        if pattern is None:
            pattern = re.compile(_MENTION_BEFORE + re.escape(needle) + after)
            self._pattern_cache[key] = pattern
        return pattern

"""AgentSkill unreferenced bundled file detection rule.

Every file bundled in a skill directory should be reachable from SKILL.md.
An unreferenced file is dead weight in the skill package and a shadow-
functionality security smell: research on malicious skills found that most
hide their behavior in bundled files SKILL.md never mentions (OWASP Agentic
Skills Top 10, AST01).

Reference semantics
-------------------

A file counts as referenced when its path or filename is mentioned in
SKILL.md or, transitively, in any local file that is itself reachable
from SKILL.md (SKILL.md -> references/a.md -> references/b.md).  Every
referenced file — not just markdown — becomes a reference source: a
data file read by a script that SKILL.md documents (SKILL.md ->
``check.py`` -> ``allowed-repos.txt``) is neither dead weight nor
hidden, because the whole chain is reviewable.  Non-markdown sources
contribute raw-text mentions only (no link resolution); binary files
(``read_text`` failure or NUL bytes) and files over 1 MiB never become
sources.

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

**Matching is case-insensitive.**  SKILL.md saying ``FORMS.md`` covers a
``forms.md`` on disk: such references work on case-insensitive
filesystems, so flagging them would be false positives.  Each source
blob is lowered once and scanned with lowered needles.

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
directory mentions must be path-ish: a trailing slash (``references/``),
a ``./`` prefix (``./canvas-fonts``), or an interior ``/``
(``assets/fonts``) — and slash-less forms only count when they resolve
to a directory that actually exists in the skill.  A bare word with no
path markers (the English word "references") is never a directory
mention.  Links may target the bare directory path.

**Python imports are followed.**  When a reachable file is a ``.py``
file, its imports are parsed (``ast.parse``, with a line-based regex
fallback for sources the parser rejects) and dotted module paths are
resolved to files within the skill — relative to the skill root and to
the importing file's directory, including relative imports (``from .
import x``, ``from ..pkg import y``).  ``from a.b import c`` marks
``a/b/c.py`` when it exists, otherwise the ``a.b`` module itself;
package ``__init__.py`` files along the dotted path are marked too.
Imported modules join the traversal, so their own text mentions and
imports are followed in turn (SKILL.md -> ``scripts/recalc.py`` ->
``from office.soffice import ...`` -> ``scripts/office/soffice.py`` ->
``schemas/foo.xsd``).  Imports inside python-labeled (or unlabeled)
fenced code blocks of reachable markdown files are followed the same
way — instructional SKILL.md fences like ``from core.gif_builder
import GIFBuilder`` reference the module as surely as a script's own
import does.

Built-in exclusions (never flagged): SKILL.md itself, README.md,
CHANGELOG.md, LICENSE* / NOTICE* (any suffix), everything under evals/
and tests/ (eval and test scaffolding is consumed by external harnesses
by convention — e.g. auth0/agent-skills ships evals.json/graders.ts
under tests/ that nothing in the skill references), ``test_*.py`` files
and anything under a ``testdata/`` directory at any depth (bundled
scripts routinely ship self-tests and fixtures nothing documents —
e.g. ai-helpers' ``scripts/test_validate.py`` + ``scripts/testdata/``),
hidden files or directories, and symlinks (which are also never
followed).  The ``exclude`` config option adds glob patterns on top of
(not replacing) these defaults.

A skill-root README.md additionally counts as a reference root alongside
SKILL.md: it is standard human-facing documentation, so a bundled file
documented there is neither dead weight nor hidden from review.
"""

import ast
import fnmatch
import os
import re
import textwrap
from collections import deque
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext, RepositoryType, _pattern_variants
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
# A slash-less directory mention ("./canvas-fonts", "assets/fonts") must
# not be followed by more path characters either — "./canvas-fonts/x.ttf"
# is a file mention, and "assets/fonts/extra" mentions a subdirectory, not
# assets/fonts.
_DIR_BARE_AFTER = r"(?![A-Za-z0-9_./-])"

_EXTERNAL_LINK_PREFIXES = ("http://", "https://", "#", "mailto:")

# Referenced files above this size never become traversal sources — a
# multi-megabyte data blob mentioning a filename is not documentation.
_SOURCE_SIZE_LIMIT = 1024 * 1024

# Fallback import-line scan for Python sources ast.parse rejects (e.g.
# Python 2 scripts).  Matches "import a.b, c" and "from .pkg import x as y, z".
_IMPORT_LINE_RE = re.compile(
    r"^[ \t]*(?:from[ \t]+([.\w]+)[ \t]+import[ \t]+([^\n#;]+)" r"|import[ \t]+([\w. \t,]+))",
    re.MULTILINE,
)

# Fenced code blocks whose info string (first word, lowercased) is one of
# these get import parsing.  Unlabeled fences are included: instructional
# markdown frequently omits the language tag, and non-Python fence content
# simply yields no resolvable imports.
_PY_FENCE_INFOS = {"", "python", "py", "python3"}


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
                "Treat a mention of a directory (e.g. `references/`, "
                "`./canvas-fonts`, or `assets/fonts` when the directory "
                "exists) as referencing every file under it"
            ),
        },
        "exclude": {
            "type": "list",
            "default": [],
            "description": (
                "Additional glob patterns (matched against skill-relative "
                "paths and bare file names; a leading `**/` also matches at "
                "the skill root) exempt from dead-file detection; "
                "extends the built-in exclusions (SKILL.md, README.md, "
                "CHANGELOG.md, LICENSE*, NOTICE*, evals/, tests/, test_*.py, "
                "testdata/, hidden files)"
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
        """All non-hidden, non-symlink files under the skill.

        Nested skill directories are pruned, and symlinks are neither
        followed nor listed: a link escaping the skill root would make
        ``resolve().relative_to()`` raise, and a symlinked markdown file
        must never pull out-of-tree content into the reference traversal.
        """
        files: List[Path] = []
        try:
            for dirpath, dirnames, filenames in os.walk(skill_path):
                base = Path(dirpath)
                dirnames[:] = sorted(
                    d
                    for d in dirnames
                    if not d.startswith(".")
                    and not (base / d).is_symlink()
                    and not (base / d / "SKILL.md").is_file()
                )
                for name in sorted(filenames):
                    if name.startswith("."):
                        continue
                    path = base / name
                    if path.is_symlink():
                        continue
                    files.append(path)
        except OSError:
            pass
        return files

    @staticmethod
    def _is_excluded(rel: str, name: str, extra_patterns: List[str]) -> bool:
        if rel == "SKILL.md":
            return True
        if name in ("README.md", "CHANGELOG.md"):
            return True
        if name.startswith(("LICENSE", "NOTICE")):
            return True
        if rel.startswith(("evals/", "tests/")):
            return True
        if name.startswith("test_") and name.endswith(".py"):
            return True
        if "testdata" in rel.split("/")[:-1]:
            return True
        for pattern in extra_patterns:
            # Same gitignore-style leading-**/ expansion as the global and
            # per-rule excludes (see context._pattern_variants, issue #322):
            # **/generated/** must also match a top-level generated/ dir.
            for variant in _pattern_variants(pattern):
                if fnmatch.fnmatch(rel, variant) or fnmatch.fnmatch(name, variant):
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
        """Files referenced from the roots, following every referenced local file."""
        skill_resolved = skill_path.resolve()
        resolved_of = {f: f.resolve() for f in all_files}
        resolved_files = set(resolved_of.values())
        rel_of = {f: resolved_of[f].relative_to(skill_resolved).as_posix() for f in all_files}
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
            if text is None or "\0" in text:
                continue  # unreadable or binary content is never a source
            # Mention matching is case-insensitive (SKILL.md saying FORMS.md
            # covers forms.md — such references work on case-insensitive
            # filesystems).  The blob is lowered once per source, outside
            # the per-candidate loop.
            text_lower = text.lower()

            newly_referenced: List[Path] = []

            # Markdown links, resolved relative to the linking file.  Link
            # syntax only means anything in markdown sources; scripts and
            # data files contribute raw-text mentions below.  Python sources
            # additionally reference the modules they import.
            direct_targets: Set[Path] = set()
            suffix = source.suffix.lower()
            if suffix == ".md":
                block = block_by_path.get(resolved_source)
                doc = block.markdown if block is not None else MarkdownDoc(text)
                link_files, link_dirs = self._link_targets(doc, source.parent, skill_resolved)
                direct_targets.update(link_files)
                if directory_covers:
                    covered_dirs.update(link_dirs)
                direct_targets.update(
                    self._fence_import_targets(
                        doc, text, resolved_source.parent, skill_resolved, resolved_files
                    )
                )
            elif suffix == ".py":
                direct_targets.update(
                    self._python_import_targets(
                        text, resolved_source.parent, skill_resolved, resolved_files
                    )
                )
            for candidate in all_files:
                if candidate in referenced:
                    continue
                if resolved_of[candidate] in direct_targets or self._text_mentions(
                    text_lower, candidate, rel_of[candidate], source.parent, skill_resolved
                ):
                    referenced.add(candidate)
                    newly_referenced.append(candidate)

            # Directory mentions in prose/code cover their contents.
            if directory_covers:
                for rel_dir in all_dirs - covered_dirs:
                    if self._dir_mentioned(text_lower, rel_dir, source.parent, skill_resolved):
                        covered_dirs.add(rel_dir)
                for candidate in all_files:
                    if candidate in referenced:
                        continue
                    rel = rel_of[candidate]
                    if any(rel.startswith(d + "/") for d in covered_dirs):
                        referenced.add(candidate)
                        newly_referenced.append(candidate)

            # Transitive traversal: every referenced file becomes a source,
            # so a data file read by a documented script is not dead
            # (SKILL.md -> check.py -> allowed-repos.txt).  Oversized files
            # are skipped; binary content is rejected when dequeued.
            for candidate in newly_referenced:
                if resolved_of[candidate] in processed:
                    continue
                try:
                    if candidate.stat().st_size > _SOURCE_SIZE_LIMIT:
                        continue
                except OSError:
                    continue
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

    # -- python imports -------------------------------------------------------

    def _fence_import_targets(
        self,
        doc: MarkdownDoc,
        text: str,
        source_dir: Path,
        skill_resolved: Path,
        resolved_files: Set[Path],
    ) -> Set[Path]:
        """Imports taught inside python (or unlabeled) fenced code blocks.

        Instructional markdown routinely shows agents how to use bundled
        modules via fences (```` ```python\\nfrom core.gif_builder import
        GIFBuilder ````), which references the module as surely as a
        script's own import does.  Fence spans come from the markdown-it
        AST (:meth:`MarkdownDoc.fences`); the content is sliced from the
        raw file text via the fence's file line range.
        """
        targets: Set[Path] = set()
        lines: Optional[List[str]] = None
        for fence in doc.fences():
            info_words = fence.info.split() if fence.info else []
            lang = info_words[0].lower() if info_words else ""
            if lang not in _PY_FENCE_INFOS:
                continue
            if lines is None:  # split the blob once, only when needed
                lines = text.split("\n")
            if fence.indented:
                start, end = fence.file_line_start - 1, fence.file_line_end
            else:  # fenced ranges include the ``` delimiter lines
                start, end = fence.file_line_start, fence.file_line_end - 1
            body = textwrap.dedent("\n".join(lines[start:end]))
            if not body.strip():
                continue
            targets.update(
                self._python_import_targets(body, source_dir, skill_resolved, resolved_files)
            )
        return targets

    def _python_import_targets(
        self,
        text: str,
        source_dir: Path,
        skill_resolved: Path,
        resolved_files: Set[Path],
    ) -> Set[Path]:
        """Bundled files reachable through this Python source's imports.

        Dotted module paths are resolved within the skill relative to the
        skill root and to the importing file's directory (bundled scripts
        are invoked from either); relative imports resolve against the
        importing file's package.  Containment is enforced by membership
        in *resolved_files* — modules outside the skill are never marked.
        """
        targets: Set[Path] = set()
        for module, names, level in self._parse_imports(text):
            parts = module.split(".") if module else []
            if level:
                base = source_dir
                for _ in range(level - 1):
                    base = base.parent
                bases = [base]
            else:
                bases = [skill_resolved]
                if source_dir != skill_resolved:
                    bases.append(source_dir)
            for base in bases:
                self._mark_module(base, parts, names, resolved_files, targets)
        return targets

    @staticmethod
    def _parse_imports(text: str) -> List[Tuple[str, List[str], int]]:
        """(module, imported names, relative level) for every import in *text*.

        Uses ``ast.parse``; sources the parser rejects (Python 2 scripts,
        templates) fall back to a line-based scan of import statements.
        """
        imports: List[Tuple[str, List[str], int]] = []
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            for match in _IMPORT_LINE_RE.finditer(text):
                if match.group(3) is not None:  # import a.b, c
                    for module in match.group(3).split(","):
                        module = module.strip()
                        if module:
                            imports.append((module, [], 0))
                else:  # from [.]a.b import c as d, e
                    module = match.group(1)
                    level = len(module) - len(module.lstrip("."))
                    names = [
                        name.strip().split(" as ")[0].strip() for name in match.group(2).split(",")
                    ]
                    imports.append(
                        (module.lstrip("."), [n for n in names if n.isidentifier()], level)
                    )
            return imports
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append((alias.name, [], 0))
            elif isinstance(node, ast.ImportFrom):
                imports.append((node.module or "", [a.name for a in node.names], node.level))
        return imports

    @staticmethod
    def _mark_module(
        base: Path,
        parts: List[str],
        names: List[str],
        resolved_files: Set[Path],
        targets: Set[Path],
    ) -> None:
        """Mark the bundled files a dotted import resolves to under *base*.

        ``import a.b`` marks ``a/b.py`` or ``a/b/__init__.py``; ``from a.b
        import c`` marks ``a/b/c.py`` when it exists, else the ``a.b``
        module itself.  Package ``__init__.py`` files along the dotted
        path execute on import, so they are marked too.  Pure set
        membership — no filesystem access.
        """

        def mark(prefix: Path) -> bool:
            module = prefix.parent / (prefix.name + ".py")
            if module in resolved_files:
                targets.add(module)
                return True
            init = prefix / "__init__.py"
            if init in resolved_files:
                targets.add(init)
                return True
            return False

        prefix = base
        for part in parts:
            prefix = prefix / part
            init = prefix / "__init__.py"
            if init in resolved_files:
                targets.add(init)

        if not names:
            mark(prefix)
            return
        for name in names:
            # `from a.b import c`: c may be a submodule or a symbol in a.b.
            if not mark(prefix / name):
                mark(prefix)

    def _text_mentions(
        self,
        text_lower: str,
        candidate: Path,
        rel: str,
        source_dir: Path,
        skill_resolved: Path,
    ) -> bool:
        """Whether the (pre-lowered) source text mentions *candidate*.

        Matching is case-insensitive: needles are lowered against the
        caller's once-per-source lowered blob, so ``FORMS.md`` in prose
        covers ``forms.md`` on disk.
        """
        needles = {rel.lower(), candidate.name.lower()}
        source_rel = self._relative_needle(candidate, source_dir, skill_resolved)
        if source_rel:
            needles.add(source_rel.lower())
        return any(
            needle in text_lower and self._pattern(needle, _FILE_AFTER).search(text_lower)
            for needle in needles
        )

    def _dir_mentioned(
        self, text_lower: str, rel_dir: str, source_dir: Path, skill_resolved: Path
    ) -> bool:
        """Whether the (pre-lowered) source text mentions the directory.

        Case-insensitive, like ``_text_mentions``.
        """
        rels = {rel_dir.lower()}
        source_rel = self._relative_needle(skill_resolved / rel_dir, source_dir, skill_resolved)
        if source_rel:
            rels.add(source_rel.lower())
        needles: Set[Tuple[str, str]] = set()
        for rel in rels:
            needles.add((rel + "/", _DIR_AFTER))
            # Slash-less path-ish forms of an existing directory also count:
            # "Search the ./canvas-fonts directory" or a nested "assets/fonts".
            # A bare word with no path markers ("data") never covers data/.
            needles.add(("./" + rel, _DIR_BARE_AFTER))
            if "/" in rel:
                needles.add((rel, _DIR_BARE_AFTER))
        return any(
            needle in text_lower and self._pattern(needle, after).search(text_lower)
            for needle, after in needles
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

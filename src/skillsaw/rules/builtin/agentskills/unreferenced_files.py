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

**Directories loaded as a whole count too.**  A directory is covered by
its bare name when a bundled script globs it (``schemas/*.xsd``), joins
it onto a base path (``Path(__file__).parent / "schemas"``), or hands
it to a call that enumerates a directory (``os.listdir('data')``,
``fs.readdirSync("assets")``, ``glob("schemas")``, ``Path("data")``) —
every file in such a directory is loaded at runtime.
anthropics/skills' ``docx`` skill reaches 117 ``.xsd`` schemas exactly
that way, through ``scripts/office/validators/base.py``.  The join
operator and the call name are what make a bare word a path: a quoted
word on its own is not one, so a JSON value (``"workload_manager":
"slurm"``) never covers a ``slurm/`` directory.

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

Built-in exclusions (never flagged, all case-insensitive): SKILL.md
itself, README / CHANGELOG (any extension), LICENSE* / NOTICE* (any
suffix — including a lowercase ``license.txt``), everything under evals/
and tests/ (eval and test scaffolding is consumed by external harnesses
by convention — e.g. auth0/agent-skills ships evals.json/graders.ts
under tests/ that nothing in the skill references), ``test_*.py`` files
and anything under a ``testdata/`` directory at any depth (bundled
scripts routinely ship self-tests and fixtures nothing documents —
e.g. ai-helpers' ``scripts/test_validate.py`` + ``scripts/testdata/``),
hidden files or directories, and symlinks (which are also never
followed). The ``exclude`` config option adds glob patterns on top of
(not replacing) these defaults.

A skill-root README.md and OpenAI ``agents/openai.yaml`` additionally count
as reference roots alongside SKILL.md: human-facing documentation and host
metadata are both legitimate entrypoints into the package.

A directory holding more than ``collapse_directory_threshold`` (default
5) unreferenced files is reported once, naming the directory and a
sample of its files, rather than once per file: a vendored schema tree
or a generated data directory is one decision for the author, and one
finding per file buries every other finding in the run.
"""

import ast
import warnings
import fnmatch
import os
import re
import textwrap
from collections import deque
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.lint_target import SkillNode
from skillsaw.markdown_doc import MarkdownDoc
from skillsaw.blocks import ContentBlock
from skillsaw.utils import read_text

from skillsaw.discovery import exact_name_exists
from skillsaw.paths import safe_is_dir, safe_is_file, safe_resolve

from ._helpers import SKILL_REPO_TYPES, contained_skill_file

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
# A nested directory's bare name ("schemas" for scripts/office/schemas) is
# only a path when it *starts* a path token, so "/" joins the excluded
# preceding characters: "http://schemas.openxmlformats.org/" and
# "vendor/schemas/x" must not cover this skill's schemas/ directory.
_DIR_NAME_BEFORE = r"(?<![A-Za-z0-9_./-])"
# A directory loaded as a whole by a bundled script: its bare name as a
# quoted segment joined onto a base path (`Path(__file__).parent /
# "schemas"`) or handed to a call that enumerates a directory
# (`os.listdir('data')`, `fs.readdirSync("assets")`, `Path("schemas")`).
# The join operator and the call name are what make it a path — a bare
# quoted word on its own is not.  A JSON value like `"workload_manager":
# "slurm"` must never cover a `slurm/` directory.
# Scanned with ``str.find`` rather than a regex: an alternation of verbs
# in front of the name has no literal to anchor on, so the engine walks
# every position of every source, and this rule already dominates the
# slowest repo in the corpus.
_QUOTES = "\"'`"
_DIR_LOAD_CALLS = (
    "listdir",
    "scandir",
    "readdir",
    "readdirsync",
    "opendir",
    "glob",
    "iglob",
    "rglob",
    "globsync",
    "path",
)

# Matched against a case-folded href: URI schemes are case-insensitive
# (RFC 3986 §3.1), so `DATA:image/png;base64,...` and `HTTPS://host/x` are
# every bit as external as their lowercase spellings.  Keep these entries
# lowercase — the fold happens on the href, not on the prefixes.
_EXTERNAL_LINK_PREFIXES = ("http://", "https://", "#", "mailto:", "data:")

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

# Above this many unreferenced files in one directory, the finding names the
# directory instead of every file in it.  A vendored schema tree is one
# decision for the author; one finding per file buries the rest of the run.
_DEFAULT_COLLAPSE_THRESHOLD = 5

# Files named in a collapsed directory finding before it says "and N more".
_COLLAPSE_SAMPLE = 3

# AST fields containing statement lists. Because import statements only appear
# at statement level, walking only these containers reaches all imports while
# avoiding traversal of expression subtrees.
_STATEMENT_LIST_FIELDS = ("body", "orelse", "finalbody", "handlers", "cases")


def _iter_statements(tree: ast.Module) -> Iterable[ast.AST]:
    """Yield all statements in *tree* across any nesting depth.

    Avoids traversing expression nodes (as ``ast.walk`` does) since imports
    only occur as statements.
    """
    stack: List[ast.AST] = list(tree.body)
    while stack:
        node = stack.pop()
        yield node
        for name in _STATEMENT_LIST_FIELDS:
            children = getattr(node, name, None)
            # Ensure children is a list of statements (avoiding single-expression fields
            # like in IfExp or Lambda).
            if isinstance(children, list):
                stack.extend(children)


_NOTICE_STEMS = ("license", "licence", "notice", "copying")
_CODE_EXTENSIONS = frozenset(
    "py js ts mjs cjs jsx tsx sh bash zsh rb go rs java kt c cc cpp h hpp cs php pl "
    "swift scala ps1 bat cmd lua".split()
)


def _is_notice_file(lowered_name: str) -> bool:
    """A license or notice document: LICENSE, LICENSES, LICENSE-MIT,
    LICENSE.APACHE, licence.txt, NOTICE.

    Documentation only — `license_check.py` and `notice_dispatch.py` are
    bundled code and stay in scope. The stem may be plural or carry a `-` or
    `.` suffix; an underscore continuation or a code extension is a program.
    """
    extension = lowered_name.rpartition(".")[2] if "." in lowered_name else ""
    if extension in _CODE_EXTENSIONS:
        return False
    for stem in _NOTICE_STEMS:
        if lowered_name.startswith(stem):
            rest = lowered_name[len(stem) :]
            if rest.startswith("s"):
                rest = rest[1:]
            if rest == "" or rest[0] in "-.":
                return True
    return False


def _ends_with_call(text_lower: str, end: int) -> bool:
    """Whether ``text_lower[:end]`` ends with a directory-loading call name
    at an identifier boundary: ``os.listdir(`` and ``glob(`` count,
    ``artifact_path(`` and ``classpath(`` do not."""
    for call in _DIR_LOAD_CALLS:
        if text_lower.endswith(call, 0, end):
            start = end - len(call)
            previous = text_lower[start - 1] if start > 0 else ""
            if not (previous.isalnum() or previous == "_"):
                return True
    return False


class AgentSkillUnreferencedFilesRule(Rule):
    # Only the collapsed directory finding carries a value: its fingerprint is
    # then rule + directory + metric, stable while files enter and leave the
    # pile, and the baseline resurfaces it only when the pile grows.
    baseline_mode = "ceiling"
    """Detect bundled skill files that SKILL.md never references"""

    repo_types = SKILL_REPO_TYPES
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
        "collapse_directory_threshold": {
            "type": "int",
            "default": _DEFAULT_COLLAPSE_THRESHOLD,
            "description": (
                "Report one finding naming the directory when it holds more "
                "than this many unreferenced files, instead of one finding "
                "per file; 0 reports every file individually"
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
        self._pattern_cache: Dict[Tuple[str, str, str], re.Pattern] = {}
        # Needle specs repeat across sources (every source asks the same
        # question about the same directories), so they are built once.
        self._dir_needle_cache: Dict[str, Tuple[Tuple[str, str, str], ...]] = {}
        directory_covers = self.setting("directory_mention_covers")
        collapse_threshold = self.setting("collapse_directory_threshold")
        if not isinstance(collapse_threshold, int) or isinstance(collapse_threshold, bool):
            collapse_threshold = _DEFAULT_COLLAPSE_THRESHOLD
        exclude_patterns = self.setting("exclude")
        if not isinstance(exclude_patterns, list) or not all(
            isinstance(pattern, str) for pattern in exclude_patterns
        ):
            exclude_patterns = []
        exclude_variants = [
            variant for pattern in exclude_patterns for variant in context.pattern_variants(pattern)
        ]

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
            # Contained, like the eval file: this README is read, and what
            # it references suppresses findings about the skill's own
            # files. A symlink out of the owning Codex plugin would let an
            # arbitrary external document decide what this rule reports.
            readme = contained_skill_file(context, skill_path, "README.md")
            if readme is not None:
                roots.append(readme)
            openai_metadata = contained_skill_file(context, skill_path, "agents", "openai.yaml")
            if openai_metadata is not None and not context.is_path_excluded(openai_metadata):
                roots.append(openai_metadata)
            referenced = self._reachable_files(
                skill_node, skill_path, roots, all_files, directory_covers
            )

            skill_resolved = safe_resolve(skill_path) or skill_path
            unreferenced: List[Tuple[str, Path]] = []
            for file_path in all_files:
                if file_path in referenced:
                    continue
                rel = (safe_resolve(file_path) or file_path).relative_to(skill_resolved).as_posix()
                if self._is_excluded(rel, file_path.name, exclude_variants):
                    continue
                unreferenced.append((rel, file_path))

            violations.extend(self._report(skill_path, unreferenced, collapse_threshold))

        return violations

    # -- reporting -----------------------------------------------------------

    def _report(
        self,
        skill_path: Path,
        unreferenced: List[Tuple[str, Path]],
        collapse_threshold: int,
    ) -> List[RuleViolation]:
        """One finding per dead file, or one per directory full of them.

        A directory holding more than *collapse_threshold* unreferenced
        files collapses to a single finding at the position of its first
        file, so the surrounding findings keep their order.
        """
        by_dir: Dict[str, List[Tuple[str, Path]]] = {}
        for rel, file_path in unreferenced:
            by_dir.setdefault(rel.rpartition("/")[0], []).append((rel, file_path))
        # The skill root never collapses: "reference the directory" is not a
        # remedy for files beside SKILL.md, so those stay one finding each.
        collapsed = (
            {
                rel_dir
                for rel_dir, group in by_dir.items()
                if rel_dir and len(group) > collapse_threshold
            }
            if collapse_threshold > 0
            else set()
        )

        violations: List[RuleViolation] = []
        reported: Set[str] = set()
        for rel, file_path in unreferenced:
            rel_dir = rel.rpartition("/")[0]
            if rel_dir not in collapsed:
                violations.append(
                    self.violation(
                        f"'{rel}' is never referenced from SKILL.md (directly or "
                        "transitively) — unreferenced files are dead weight and "
                        "can hide unreviewed behavior",
                        file_path=file_path,
                    )
                )
                continue
            if rel_dir in reported:
                continue
            reported.add(rel_dir)
            violations.append(self._directory_violation(skill_path, rel_dir, by_dir[rel_dir]))
        return violations

    def _directory_violation(
        self, skill_path: Path, rel_dir: str, group: List[Tuple[str, Path]]
    ) -> RuleViolation:
        names = sorted(file_path.name for _, file_path in group)
        sample = ", ".join(names[:_COLLAPSE_SAMPLE])
        if len(names) > _COLLAPSE_SAMPLE:
            sample += f", and {len(names) - _COLLAPSE_SAMPLE} more"
        return self.violation(
            f"{len(names)} unreferenced files under '{rel_dir}/' ({sample}) — dead "
            "weight that can hide unreviewed behavior; reference the directory "
            "from SKILL.md, or exclude it",
            file_path=skill_path / rel_dir,
            # A ratchet: the fingerprint is rule + directory + metric, so a
            # baselined pile does not resurface when its names change, only
            # when it grows past the baselined count.
            value=float(len(names)),
            metric="unreferenced-directory",
        )

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
                # Same nested-skill predicate as discovery: a subdirectory
                # with a mis-cased skill.md is not a nested skill, so its
                # files stay in this skill's scan on every filesystem.
                dirnames[:] = sorted(
                    d
                    for d in dirnames
                    if not d.startswith(".")
                    and not (base / d).is_symlink()
                    and not exact_name_exists(base / d, "SKILL.md")
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
    def _is_excluded(rel: str, name: str, extra_variants: List[str]) -> bool:
        """Return whether a bundled path matches built-in or configured exclusions."""
        if rel == "SKILL.md":
            return True
        # Case-insensitive, and independent of extension: a lowercase
        # `license.txt` or a `README.rst` is the same human-facing file as
        # the spelling the convention suggests, and flagging it as dead
        # weight was pure noise (5,009 corpus findings included plain
        # `license.txt` files).
        lowered = name.lower()
        if _is_notice_file(lowered):
            return True
        if (lowered.rpartition(".")[0] or lowered) in ("readme", "changelog"):
            return True
        rel_lower = rel.lower()
        if rel_lower.startswith(("evals/", "tests/")):
            return True
        if lowered.startswith("test_") and lowered.endswith(".py"):
            return True
        if "testdata" in rel_lower.split("/")[:-1]:
            return True
        # Same gitignore-style leading-**/ expansion as the global and
        # per-rule excludes (see RepositoryContext.pattern_variants, issue
        # #322): **/generated/** must also match a top-level generated/ dir.
        for variant in extra_variants:
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
        skill_resolved = safe_resolve(skill_path) or skill_path
        resolved_of = {f: (safe_resolve(f) or f) for f in all_files}
        resolved_files = set(resolved_of.values())
        rel_of = {f: resolved_of[f].relative_to(skill_resolved).as_posix() for f in all_files}
        # Per-skill, not per (source, candidate) pair: needles and their
        # lowered spellings are identical for every source that asks.
        needles_of = {f: (rel_of[f].lower(), f.name.lower()) for f in all_files}
        files_by_dir = self._files_by_dir(all_files, rel_of)
        all_dirs = set(files_by_dir)
        dir_specs = {rel_dir: self._dir_specs(rel_dir) for rel_dir in all_dirs}
        block_by_path = {block.resolved_path: block for block in skill_node.find(ContentBlock)}

        root_paths = {(safe_resolve(root) or root) for root in roots}
        referenced: Set[Path] = {
            candidate for candidate in all_files if resolved_of[candidate] in root_paths
        }
        covered_dirs: Set[str] = set()
        queue: deque = deque(roots)
        processed: Set[Path] = set()

        while queue:
            source = queue.popleft()
            resolved_source = safe_resolve(source) or source
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
            # The mentioning file's directory, as a skill-relative POSIX
            # string: relative needles are string slices off it, not
            # ``os.path.relpath`` round-trips through ``Path`` (the audit
            # profile spent 53 s of 116 s building those).
            source_dir_rel = self._skill_relative_dir(resolved_source, skill_resolved)

            # Markdown links, resolved relative to the linking file.  Link
            # syntax only means anything in markdown sources; scripts and
            # data files contribute raw-text mentions below.  Python sources
            # additionally reference the modules they import.
            direct_targets: Set[Path] = set()
            newly_covered: Set[str] = set()
            suffix = source.suffix.lower()
            if suffix == ".md":
                block = block_by_path.get(resolved_source)
                doc = block.markdown if block is not None else MarkdownDoc(text)
                link_files, link_dirs = self._link_targets(doc, source.parent, skill_resolved)
                direct_targets.update(link_files)
                if directory_covers:
                    newly_covered.update(link_dirs)
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
                rel_lower, name_lower = needles_of[candidate]
                if resolved_of[candidate] in direct_targets or self._text_mentions(
                    text_lower, rel_lower, name_lower, source_dir_rel
                ):
                    referenced.add(candidate)
                    newly_referenced.append(candidate)

            # Directory mentions in prose/code cover their contents.
            if directory_covers:
                for rel_dir in all_dirs:
                    if rel_dir in covered_dirs or rel_dir in newly_covered:
                        continue
                    if self._dir_mentioned(text_lower, dir_specs[rel_dir], rel_dir, source_dir_rel):
                        newly_covered.add(rel_dir)
                for rel_dir in sorted(newly_covered):
                    if rel_dir in covered_dirs:
                        continue
                    covered_dirs.add(rel_dir)
                    for candidate in files_by_dir.get(rel_dir, ()):
                        if candidate in referenced:
                            continue
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
    def _files_by_dir(all_files: List[Path], rel_of: Dict[Path, str]) -> Dict[str, List[Path]]:
        """Every candidate directory mapped to the files anywhere beneath it.

        Covering a directory then costs one dict lookup instead of a scan
        of every bundled file against every covered directory.
        """
        by_dir: Dict[str, List[Path]] = {}
        for candidate in all_files:
            parts = rel_of[candidate].split("/")[:-1]
            for i in range(1, len(parts) + 1):
                by_dir.setdefault("/".join(parts[:i]), []).append(candidate)
        return by_dir

    @staticmethod
    def _skill_relative_dir(resolved_source: Path, skill_resolved: Path) -> str:
        """The mentioning file's directory, skill-relative; "" at the root."""
        try:
            return resolved_source.relative_to(skill_resolved).as_posix().rpartition("/")[0]
        except ValueError:
            return ""

    @staticmethod
    def _link_targets(
        doc: MarkdownDoc, base_dir: Path, skill_resolved: Path
    ) -> Tuple[Set[Path], Set[str]]:
        """Resolve local link targets to (files, skill-relative directories)."""
        files: Set[Path] = set()
        dirs: Set[str] = set()
        for link in doc.links():
            target = link.href.strip()
            if not target or target.casefold().startswith(_EXTERNAL_LINK_PREFIXES):
                continue
            target = target.split("#")[0]
            if not target:
                continue
            # ``safe_resolve`` rather than a bare ``.resolve()``: a symlink
            # loop raises RuntimeError before Python 3.13 and OSError from
            # 3.13 on, and this project supports 3.9 through 3.14. An
            # escaping RuntimeError turns the rule into a
            # rule-execution-error and discards all its findings.
            resolved = safe_resolve(base_dir / target)
            if resolved is None:
                continue
            if not resolved.is_relative_to(skill_resolved) or resolved == skill_resolved:
                continue
            # ``safe_is_dir`` / ``safe_is_file`` rather than the raw
            # predicates: ``resolve()`` does not stat the final component, so
            # a link href like a ``data:image/png;base64,...`` URI (which is
            # not caught by _EXTERNAL_LINK_PREFIXES if a new scheme appears)
            # resolves to a path whose final component is thousands of
            # characters long, and ``is_dir()`` / ``is_file()`` then raise
            # ``ENAMETOOLONG`` — a raw OSError that turns the rule into a
            # rule-execution-error and discards every finding for the repo.
            if safe_is_dir(resolved):
                dirs.add(resolved.relative_to(skill_resolved).as_posix())
            elif safe_is_file(resolved):
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
        if "import" not in text:
            return imports  # Quick check: skip parsing if "import" is not present in text
        try:
            # A bundled script with an invalid escape (`"\\d"`) makes
            # ast.parse emit `<unknown>:N: SyntaxWarning` on stderr — noise
            # about the skill's helper, in the middle of the lint output.
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
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
        for node in _iter_statements(tree):
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
        rel_lower: str,
        name_lower: str,
        source_dir_rel: str,
    ) -> bool:
        """Whether the (pre-lowered) source text mentions the candidate.

        Matching is case-insensitive: needles are lowered against the
        caller's once-per-source lowered blob, so ``FORMS.md`` in prose
        covers ``forms.md`` on disk.
        """
        if self._matches(text_lower, rel_lower, _FILE_AFTER, _MENTION_BEFORE):
            return True
        if name_lower != rel_lower and self._matches(
            text_lower, name_lower, _FILE_AFTER, _MENTION_BEFORE
        ):
            return True
        source_rel = self._relative_under(rel_lower, source_dir_rel)
        return (
            source_rel is not None
            and source_rel != name_lower
            and self._matches(text_lower, source_rel, _FILE_AFTER, _MENTION_BEFORE)
        )

    def _dir_mentioned(
        self,
        text_lower: str,
        dir_spec: Tuple[str, Tuple[Tuple[str, str, str], ...]],
        rel_dir: str,
        source_dir_rel: str,
    ) -> bool:
        """Whether the (pre-lowered) source text mentions the directory.

        *dir_spec* holds the directory's bare name and the skill-relative
        needles, built once per skill; only the needle relative to the
        mentioning file's own directory depends on the source.
        Case-insensitive, like ``_text_mentions``.
        """
        name, specs = dir_spec
        if any(self._matches(text_lower, needle, after, before) for needle, after, before in specs):
            return True
        if self._loaded_as_quoted_segment(text_lower, name):
            return True
        source_rel = self._relative_under(rel_dir.lower(), source_dir_rel)
        if source_rel is None:
            return False
        return any(
            self._matches(text_lower, needle, after, before)
            for needle, after, before in self._path_dir_specs(source_rel)
        )

    @staticmethod
    def _loaded_as_quoted_segment(text_lower: str, name: str) -> bool:
        """Whether a quoted *name* is joined onto a path or enumerated.

        ``Path(__file__).parent / "schemas"`` and ``os.listdir('data')``
        load the whole directory; ``"workload_manager": "slurm"`` is a
        config value that happens to spell a directory name.  The join
        operator and the call name are the difference.
        """
        start = text_lower.find(name)
        while start != -1:
            end = start + len(name)
            if (
                start
                and text_lower[start - 1] in _QUOTES
                and end < len(text_lower)
                and text_lower[end] in _QUOTES
            ):
                before = start - 2
                while before >= 0 and text_lower[before] in " \t":
                    before -= 1
                if before >= 0:
                    if text_lower[before] == "/":
                        return True
                    if text_lower[before] == "(" and _ends_with_call(text_lower, before):
                        return True
            start = text_lower.find(name, end)
        return False

    def _dir_specs(self, rel_dir: str) -> Tuple[str, Tuple[Tuple[str, str, str], ...]]:
        """The directory's bare name and the needles covering it as a whole."""
        lowered = rel_dir.lower()
        specs = list(self._path_dir_specs(lowered))
        name = lowered.rpartition("/")[2]
        if name != lowered:
            # A nested directory is also reached by its bare name when a
            # script globs it (`schemas/*.xsd`) — a top-level directory's
            # bare name is already covered by the path forms above.
            specs.append((name + "/", _DIR_AFTER, _DIR_NAME_BEFORE))
        return name, tuple(specs)

    def _path_dir_specs(self, rel: str) -> Tuple[Tuple[str, str, str], ...]:
        """Path-ish needles for a (lowered) directory path, memoized."""
        cached = self._dir_needle_cache.get(rel)
        if cached is None:
            specs = [
                (rel + "/", _DIR_AFTER, _MENTION_BEFORE),
                # Slash-less path-ish forms of an existing directory also
                # count: "Search the ./canvas-fonts directory" or a nested
                # "assets/fonts".  A bare word with no path markers ("data")
                # is never a path-ish mention.
                ("./" + rel, _DIR_BARE_AFTER, _MENTION_BEFORE),
            ]
            if "/" in rel:
                specs.append((rel, _DIR_BARE_AFTER, _MENTION_BEFORE))
            cached = tuple(specs)
            self._dir_needle_cache[rel] = cached
        return cached

    @staticmethod
    def _relative_under(rel: str, source_dir_rel: str) -> Optional[str]:
        """*rel* rewritten relative to the mentioning file's directory.

        Lets ``references/a.md`` reference ``references/img/x.png`` as
        ``img/x.png``.  ``None`` when the target is not under that
        directory — an upward (``..``) path never matched anyway, and at
        the skill root the relative needle equals the skill-relative one.
        """
        if not source_dir_rel:
            return None
        if rel == source_dir_rel:
            return "."  # a source's own directory, mentioned as "./"
        prefix = source_dir_rel + "/"
        return rel[len(prefix) :] if rel.startswith(prefix) else None

    def _matches(self, text_lower: str, needle: str, after: str, before: str) -> bool:
        """Boundary-aware search, gated on a plain substring check first."""
        return needle in text_lower and bool(
            self._pattern(needle, after, before).search(text_lower)
        )

    def _pattern(self, needle: str, after: str, before: str) -> re.Pattern:
        key = (needle, after, before)
        pattern = self._pattern_cache.get(key)
        if pattern is None:
            pattern = re.compile(before + re.escape(needle) + after)
            self._pattern_cache[key] = pattern
        return pattern

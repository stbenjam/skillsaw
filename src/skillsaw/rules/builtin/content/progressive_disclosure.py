"""Content progressive disclosure rule.

``context-budget`` says a file is too big; this rule says what to do about
it.  Anthropic's Claude 5 context-engineering guidance is to divide long
skills into many files loaded on demand ("progressive disclosure") and to
keep CLAUDE.md lightweight, deferring detail to skills and imports.  A file
that is over its token budget *and* references no other local file has not
even started that split, so the two findings deserve different advice:
"trim this" versus "split this and link the pieces".

What counts as a disclosure reference differs by surface:

* **Skills** bundle their own material, so only references into the
  bundle count: markdown links resolving inside the skill directory,
  path-like tokens (``references/guide.md``, ``scripts/run.py``) that
  name a file bundled with the skill — including inside fenced code
  blocks, where bundled scripts are typically invoked — and bare
  filename mentions of bundled files ("run helper.py").
* **Instruction files** (CLAUDE.md, AGENTS.md, GEMINI.md, and friends)
  disclose through explicit markdown links to local files and ``@path``
  imports.  Bare path mentions deliberately do not count: "``src/api/``
  contains the handlers" is structure narration, not an instruction to
  load a file on demand.

The rule only inspects files already over a budget threshold, so its
scans run on a handful of files per repository at most.
"""

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple
from urllib.parse import unquote

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.blocks import ContentBlock
from skillsaw.paths import safe_exists, safe_resolve
from skillsaw.rules.builtin.content_analysis import gather_all_content_blocks
from skillsaw.rules.builtin.context_budget.budget import DEFAULT_LIMITS
from skillsaw.rules.builtin.instructions._helpers import _IMPORT_RE
from skillsaw.rules.builtin.utils import read_text

# Thresholds default to the context-budget warn limits so the two rules
# agree on when a file is "long".  Users can raise/lower per category or
# extend the rule to other categories (e.g. ``command: 2000``) via the
# ``limits`` config option.
_DEFAULT_CATEGORIES = ("skill", "claude-md", "agents-md", "gemini-md", "instruction")
DEFAULT_THRESHOLDS: Dict[str, int] = {
    category: DEFAULT_LIMITS[category]["warn"] for category in _DEFAULT_CATEGORIES
}

# Same scheme/anchor skip set as content-broken-internal-reference: two-plus
# characters before the colon so a Windows drive path stays a file path.
_URI_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]+:")

# Slash or ./ path forms mentioned anywhere in a skill body, fences
# included — bundled scripts are usually invoked, not linked.
_PATH_TOKEN_RE = re.compile(r"(?:\./)?[\w.-]+(?:/[\w.-]+)+")

# Bare-filename mentions must sit on token boundaries: `run.py` must not
# match inside `myrun.py` or `run.pyc` (same boundaries as
# agentskill-unreferenced-files).
_MENTION_BEFORE = r"(?<![A-Za-z0-9_-])"
_MENTION_AFTER = r"(?![A-Za-z0-9_-]|\.[A-Za-z0-9])"

# Bundled files that are packaging scaffolding, not disclosure targets.
_SCAFFOLDING_NAMES = {"SKILL.md", "README.md", "CHANGELOG.md"}
_SCAFFOLDING_PREFIXES = ("LICENSE", "NOTICE")


class ContentProgressiveDisclosureRule(Rule):
    """Long files should split detail into referenced files that load on demand"""

    formats = None
    repo_types = None
    default_enabled = "auto"
    since = "0.19.0"
    baseline_mode = "ceiling"

    config_schema = {
        "limits": {
            "type": "dict",
            "default": DEFAULT_THRESHOLDS,
            "description": (
                "Token thresholds per file category above which a file with "
                "no local file references is flagged; add a category "
                "(e.g. command) to extend the rule to it, set one to a "
                "higher value to relax it"
            ),
        },
    }

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        merged: Dict[str, Any] = dict(DEFAULT_THRESHOLDS)
        merged.update(self.config.get("limits", {}) or {})
        self._limits: Dict[str, int] = {}
        for category, value in merged.items():
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(
                    f"'limits' values for rule '{self.rule_id}' must be integers, "
                    f"got {type(value).__name__} for '{category}'"
                )
            self._limits[category] = value

    @property
    def rule_id(self) -> str:
        return "content-progressive-disclosure"

    @property
    def description(self) -> str:
        return (
            "Long skills and instruction files should use progressive disclosure: "
            "split detail into referenced files that load on demand"
        )

    def default_severity(self) -> Severity:
        return Severity.INFO

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        # Per-run cache: bare-name mention patterns repeat across skills
        # that bundle files with the same names (run.py, guide.md, ...).
        self._pattern_cache: Dict[str, re.Pattern] = {}
        root = safe_resolve(context.root_path) or context.root_path
        violations: List[RuleViolation] = []
        for cf in gather_all_content_blocks(context):
            limit = self._limits.get(cf.category)
            if limit is None:
                continue
            content = read_text(cf.path)
            if content is None:
                continue
            tokens = len(content) // 4  # same estimate as context-budget
            if tokens <= limit:
                continue
            if self._has_disclosure_reference(cf, root):
                continue
            if cf.category == "skill":
                advice = (
                    "split detailed material into bundled files (references/*.md, "
                    "scripts) and point to them from SKILL.md so detail loads "
                    "only when needed"
                )
            else:
                advice = (
                    "move detail into skills, rules, or files pulled in via "
                    "markdown links or @imports so it loads on demand"
                )
            violations.append(
                self.violation(
                    f"Estimated {tokens:,} tokens exceeds the {limit:,}-token "
                    f"progressive-disclosure threshold for {cf.category} and the "
                    f"file references no other local file — {advice}",
                    block=cf,
                    value=tokens,
                )
            )
        return violations

    # -- reference detection -------------------------------------------------

    def _has_disclosure_reference(self, cf: ContentBlock, root: Path) -> bool:
        self_path = safe_resolve(cf.path) or cf.path
        # A skill's disclosure surface is its own bundle: links and imports
        # must land inside the skill directory (the same containment as
        # agentskill-unreferenced-files), so an oversized skill cannot
        # silence the finding by pointing at an unrelated repo file.
        boundary = self_path.parent if cf.category == "skill" else root
        if self._has_local_link(cf, boundary, self_path):
            return True
        body = cf.read_body(strip_code_blocks=False) or ""
        if self._has_import_reference(cf, body, boundary, self_path):
            return True
        if cf.category != "skill":
            return False
        return self._has_bundled_mention(body, self_path.parent)

    def _has_local_link(self, cf: ContentBlock, boundary: Path, self_path: Path) -> bool:
        """A markdown link resolving to a local file or directory in *boundary*."""
        for link in cf.markdown.links():
            target = link.href.strip()
            if not target or target.startswith(("#", "//")) or _URI_SCHEME.match(target):
                continue
            target = unquote(target.split("#")[0])
            if not target:
                continue
            resolved = safe_resolve(cf.path.parent / target)
            if resolved is None or resolved == self_path:
                continue
            if not resolved.is_relative_to(boundary):
                continue
            if safe_exists(resolved):
                return True
        return False

    def _has_import_reference(
        self, cf: ContentBlock, body: str, boundary: Path, self_path: Path
    ) -> bool:
        """An ``@path`` import resolving to an existing path in *boundary*.

        Directory imports count too — ``instruction-imports-valid``
        accepts ``@docs`` when the directory exists, so a file that has
        split its detail into an imported directory must not be flagged.
        Only tokens that resolve inside the boundary count — an
        ``@octocat`` mention or a ``@~/.claude/...`` home import is not
        disclosure this rule can credit.
        """
        if "@" not in body:
            return False
        for _line_num, line in cf.markdown.prose_lines():
            if "@" not in line:
                continue
            for match in _IMPORT_RE.finditer(line):
                import_path = match.group(1).rstrip(".!?")
                if not import_path or import_path.startswith("~"):
                    continue
                resolved = safe_resolve(cf.path.parent / import_path)
                if resolved is None or resolved == self_path:
                    continue
                if not resolved.is_relative_to(boundary):
                    continue
                if safe_exists(resolved):
                    return True
        return False

    def _has_bundled_mention(self, body: str, skill_dir: Path) -> bool:
        """The body mentions a bundled file by relative path or bare name.

        Bundled files are enumerated once and matched by set membership
        against the body's path-like tokens — a mention only counts when
        it names a file that actually ships with the skill, so no
        per-token filesystem probing is needed (matters on multi-thousand-
        token bodies full of URLs and example paths).  Case-insensitive,
        like agentskill-unreferenced-files.
        """
        rel_paths, names = self._bundled_inventory(skill_dir)
        if not rel_paths:
            return False
        body_lower = body.lower()
        for match in _PATH_TOKEN_RE.finditer(body_lower):
            token = match.group(0).rstrip(".")
            if token.startswith("./"):
                token = token[2:]
            if token in rel_paths:
                return True
        for name in names:
            if name not in body_lower:
                continue
            pattern = self._mention_pattern(name)
            if pattern.search(body_lower):
                return True
        return False

    def _mention_pattern(self, needle: str) -> re.Pattern:
        pattern = self._pattern_cache.get(needle)
        if pattern is None:
            pattern = re.compile(_MENTION_BEFORE + re.escape(needle) + _MENTION_AFTER)
            self._pattern_cache[needle] = pattern
        return pattern

    @staticmethod
    def _bundled_inventory(skill_dir: Path) -> Tuple[Set[str], Set[str]]:
        """(relative posix paths, bare names) of disclosure-eligible bundled
        files, lowercased.

        Hidden entries, symlinks, nested skills, and packaging scaffolding
        (SKILL.md, README.md, licenses) are skipped.  Extensionless files
        (``scripts/deploy``) stay matchable by relative path, but only
        names carrying an extension become bare-name candidates — a
        mention of "deploy" alone is a word, not unambiguously a file.
        """
        rel_paths: Set[str] = set()
        names: Set[str] = set()
        try:
            for dirpath, dirnames, filenames in os.walk(skill_dir):
                base = Path(dirpath)
                dirnames[:] = sorted(
                    d
                    for d in dirnames
                    if not d.startswith(".")
                    and not (base / d).is_symlink()
                    and not (base / d / "SKILL.md").is_file()
                )
                for name in filenames:
                    if name.startswith("."):
                        continue
                    if name in _SCAFFOLDING_NAMES or name.startswith(_SCAFFOLDING_PREFIXES):
                        continue
                    if (base / name).is_symlink():
                        continue
                    rel = (base / name).relative_to(skill_dir).as_posix()
                    rel_paths.add(rel.lower())
                    if "." in name.strip("."):
                        names.add(name.lower())
        except OSError:
            pass
        return rel_paths, names

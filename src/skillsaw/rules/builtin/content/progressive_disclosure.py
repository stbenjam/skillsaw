"""Content progressive disclosure rule.

``context-budget`` says a file is too big; this rule says what to do about
it.  Anthropic's Claude 5 context-engineering guidance is to divide large
skills into many files loaded on demand ("progressive disclosure") and to
keep instruction files lightweight, deferring detail to skills and imports.
A file that is over its token budget *and* references no other local file
has not even started that split, so the two findings deserve different
advice: "trim this" versus "split this and link the pieces".

What counts as a disclosure reference differs by surface:

* **Skills** bundle their own material, so only references into the
  bundle count: markdown links to disclosure-eligible bundled files (or
  directories holding them), path-like tokens (``references/guide.md``,
  ``scripts/run.py``) that name a file bundled with the skill —
  including inside fenced code blocks, where bundled scripts are
  typically invoked — and bare filename mentions of bundled files ("run
  helper.py").  Image embeds, scaffolding (README.md), test/eval
  scaffolding, and nested skills' files never count.
* **Instruction files** disclose through explicit markdown links to
  local files, and — only for hosts that actually load imports
  (CLAUDE.md, AGENTS.md, GEMINI.md, QWEN.md) — ``@path`` imports (files or
  imported directories).  Bare path mentions and directory links
  deliberately do not count: "``src/api/`` contains the handlers" and
  "see [src](src/)" are structure narration, not an instruction to load
  a file on demand.

The rule only inspects files already over a budget threshold, so its
scans run on a handful of files per repository at most.
"""

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import unquote

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.blocks import ContentBlock
from skillsaw.discovery import exact_name_exists
from skillsaw.paths import safe_exists, safe_is_file, safe_resolve
from skillsaw.rules.builtin.content_analysis import gather_all_content_blocks
from skillsaw.rules.builtin.context_budget.budget import DEFAULT_LIMITS, _estimate_tokens
from skillsaw.rules.builtin.instructions._helpers import IMPORT_RE

# Thresholds default to the context-budget warn limits so the two rules
# agree on when a file is "long" — except skills, whose threshold is
# raised to 6k: real-world skills in the 3-6k range routinely work fine
# as a single file, and the split-and-link advice only pays for itself
# above that.  Users can raise/lower per category or extend the rule to
# other categories (e.g. ``agent: 2000``) via the ``limits`` config
# option.
_DEFAULT_CATEGORIES = (
    "skill",
    "claude-md",
    "agents-md",
    "gemini-md",
    "qwen-md",
    "instruction",
)
DEFAULT_THRESHOLDS: Dict[str, int] = {
    category: DEFAULT_LIMITS[category]["warn"] for category in _DEFAULT_CATEGORIES
}
DEFAULT_THRESHOLDS["skill"] = 6000

# Same scheme/anchor skip set as content-broken-internal-reference: two-plus
# characters before the colon so a Windows drive path stays a file path.
_URI_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]+:")

# Slash or ./ path forms mentioned anywhere in a skill body, fences
# included — bundled scripts are usually invoked, not linked.  The
# lookbehind keeps a match from restarting mid-path: `/scripts/run.py`
# and `C:/scripts/run.py` are absolute/foreign paths whose suffix must
# not be mistaken for the bundled relative path `scripts/run.py`.
_PATH_TOKEN_RE = re.compile(r"(?<![\w./\\-])((?:\./)?[\w.-]+(?:[/\\][\w.-]+)+)")

# Quoted path forms may contain spaces (`cat "references/setup guide.md"`);
# the quotes delimit the token where whitespace otherwise would.
_QUOTED_PATH_RE = re.compile(r"""["']((?:\./)?[^"'\n/\\]+(?:[/\\][^"'\n/\\]+)+)["']""")

# Bare-filename mentions must sit on token boundaries: `run.py` must not
# match inside `myrun.py` or `run.pyc` (same after-boundary as
# agentskill-unreferenced-files).  The before-boundary additionally
# rejects `/` and `.`: a slash-preceded name is a path segment, and any
# genuine bundled path already matched the rel-path set, so what remains
# is a URL or foreign path ending in a bundled file's name
# (https://example.com/docs/deploy.md must not credit references/deploy.md).
_MENTION_BEFORE = r"(?<![A-Za-z0-9_./-])"
_MENTION_AFTER = r"(?![A-Za-z0-9_-]|\.[A-Za-z0-9])"

# Bundled files that are packaging scaffolding, not disclosure targets.
_SCAFFOLDING_NAMES = {"SKILL.md", "README.md", "CHANGELOG.md"}
_SCAFFOLDING_PREFIXES = ("LICENSE", "NOTICE")

# Categories whose host actually loads ``@path`` imports — the same
# surface instruction-imports-valid validates.  In a generic instruction
# file (.cursorrules, copilot-instructions.md) an ``@docs`` token is
# just prose, so it must not count as disclosure there.
_IMPORT_CATEGORIES = frozenset({"claude-md", "agents-md", "gemini-md", "qwen-md"})


class ContentProgressiveDisclosureRule(Rule):
    """Large files should split detail into referenced files that load on demand"""

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
                "(e.g. agent) to extend the rule to it, set one higher to "
                "relax it, or set one to null to opt the category out. "
                "context-budget's {warn: N} shape is accepted (warn is used)"
            ),
        },
    }

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        raw = self.config.get("limits", {})
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise ValueError(
                f"'limits' for rule '{self.rule_id}' must be a mapping of "
                f"category to token threshold, got {type(raw).__name__}"
            )
        merged: Dict[str, Any] = dict(DEFAULT_THRESHOLDS)
        merged.update(raw)
        self._limits: Dict[str, int] = {}
        for category, value in merged.items():
            threshold = self._parse_threshold(category, value)
            if threshold is not None:
                self._limits[category] = threshold
        self._pattern_cache: Dict[str, re.Pattern] = {}

    def _parse_threshold(self, category: str, value: Any) -> Optional[int]:
        """Parse one category's threshold.

        Accepts an int, ``null``/``False`` to opt the category out, or
        context-budget's ``{warn: N}`` dict shape (users copy their
        existing limits block; the warn threshold is the one this rule
        mirrors).
        """
        if value is None or value is False:
            return None
        if isinstance(value, dict):
            value = value.get("warn")
            if value is None:
                return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(
                f"'limits' values for rule '{self.rule_id}' must be integers, "
                f"null, or {{warn: N}}, got {type(value).__name__} for '{category}'"
            )
        if value < 0:
            raise ValueError(
                f"'limits' values for rule '{self.rule_id}' must be non-negative, "
                f"got {value} for '{category}'"
            )
        return value

    @property
    def rule_id(self) -> str:
        return "content-progressive-disclosure"

    @property
    def description(self) -> str:
        return (
            "Large skills and instruction files should use progressive disclosure: "
            "split detail into referenced files that load on demand"
        )

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        # Per-run cache: bare-name mention patterns repeat across skills
        # that bundle files with the same names (run.py, guide.md, ...).
        self._pattern_cache.clear()
        root = safe_resolve(context.root_path) or context.root_path
        violations: List[RuleViolation] = []
        for cf in gather_all_content_blocks(context):
            limit = self._limits.get(cf.category)
            if limit is None:
                continue
            # Measure the block's own body, not its file: configured extra
            # categories can put several blocks in one file (a promptfoo
            # config holds one block per prompt), and measurement must
            # cover the same prose unit reference detection scans.
            body = cf.read_body(strip_code_blocks=False)
            if body is None:
                continue
            tokens = _estimate_tokens(body)
            if tokens <= limit:
                continue
            if self._has_disclosure_reference(cf, body, root):
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
                    "markdown links or @imports (where your tool supports "
                    "them) so it loads on demand"
                )
            metric = getattr(cf, "yaml_path", None) or None
            violations.append(
                self.violation(
                    f"Estimated {tokens:,} tokens exceeds the {limit:,}-token "
                    f"progressive-disclosure threshold for {cf.category} and the "
                    f"file references no other local file — {advice}",
                    block=cf,
                    value=tokens,
                    metric=metric,
                )
            )
        return violations

    # -- reference detection -------------------------------------------------

    def _has_disclosure_reference(self, cf: ContentBlock, body: str, root: Path) -> bool:
        self_path = safe_resolve(cf.path) or cf.path
        # A skill's disclosure surface is its own bundle: links and imports
        # must land inside the skill directory (the same containment as
        # agentskill-unreferenced-files), so an oversized skill cannot
        # silence the finding by pointing at an unrelated repo file.
        is_skill = cf.category == "skill"
        boundary = self_path.parent if is_skill else root
        inventory = self._bundled_inventory(self_path.parent) if is_skill else None
        if self._has_local_link(cf, boundary, self_path, inventory=inventory):
            return True
        if cf.category in _IMPORT_CATEGORIES and self._has_import_reference(
            cf, body, boundary, self_path
        ):
            return True
        if inventory is None:
            return False
        masked = self._mask_image_destinations(cf, body)
        masked = self._mask_html_comments(cf, masked)
        return self._has_bundled_mention(masked, *inventory)

    def _has_local_link(
        self,
        cf: ContentBlock,
        boundary: Path,
        self_path: Path,
        *,
        inventory: Optional[Tuple[Set[str], Set[str]]],
    ) -> bool:
        """A markdown link resolving to a local file inside *boundary*.

        Images never count — an embedded diagram is rendered, not loaded
        on demand.  For skills (*inventory* given), the target must be a
        disclosure-eligible bundled file, or a directory holding one:
        scaffolding (README.md) and nested skills' files sit inside the
        skill directory but are not the skill's own disclosed material.
        For instruction files a directory link ("see [src](src/)") is
        structure narration, not on-demand loading.  The boundary
        directory itself never counts — ``[.](.)`` discloses nothing.
        """
        for link in cf.markdown.links():
            if link.is_image:
                continue
            target = link.href.strip()
            if not target or target.startswith(("#", "//")) or _URI_SCHEME.match(target):
                continue
            target = target.split("#")[0]
            if not target:
                continue
            # Decode percent-escapes for the lookup, but keep accepting a
            # file whose literal name contains %XX and is linked verbatim
            # (the same fallback as content-broken-internal-reference).
            candidates = [unquote(target)]
            if candidates[0] != target:
                candidates.append(target)
            for candidate in candidates:
                if not candidate:
                    continue
                resolved = safe_resolve(cf.path.parent / candidate)
                if resolved is None or resolved == self_path or resolved == boundary:
                    continue
                if not resolved.is_relative_to(boundary):
                    continue
                if inventory is None:
                    if safe_is_file(resolved):
                        return True
                    continue
                rel_paths, _names = inventory
                rel = resolved.relative_to(boundary).as_posix().lower()
                if rel in rel_paths:
                    return True
                if any(bundled.startswith(rel + "/") for bundled in rel_paths):
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
            for match in IMPORT_RE.finditer(line):
                import_path = match.group(1).rstrip(".!?")
                if not import_path or import_path.startswith("~"):
                    continue
                resolved = safe_resolve(cf.path.parent / import_path)
                if resolved is None or resolved == self_path or resolved == boundary:
                    continue
                if not resolved.is_relative_to(boundary):
                    continue
                if safe_exists(resolved):
                    return True
        return False

    def _has_bundled_mention(self, body: str, rel_paths: Set[str], names: Set[str]) -> bool:
        """The body mentions a bundled file by relative path or bare name.

        Matched by set membership against the body's path-like tokens —
        a mention only counts when it names a file that actually ships
        with the skill, so no per-token filesystem probing is needed
        (matters on multi-thousand-token bodies full of URLs and example
        paths).  Case-insensitive, like agentskill-unreferenced-files.
        """
        if not rel_paths:
            return False
        body_lower = body.lower()
        for pattern in (_PATH_TOKEN_RE, _QUOTED_PATH_RE):
            for match in pattern.finditer(body_lower):
                token = match.group(1).rstrip(".")
                if token.startswith("./"):
                    token = token[2:]
                token = token.replace("\\", "/")
                if token in rel_paths:
                    return True
        for name in names:
            if name not in body_lower:
                continue
            pattern = self._mention_pattern(name)
            if pattern.search(body_lower):
                return True
        return False

    @staticmethod
    def _mask_image_destinations(cf: ContentBlock, body: str) -> str:
        """*body* with image destination spans blanked out.

        ``_has_local_link`` refuses image links because an embedded
        diagram is rendered, not loaded on demand; the raw-body mention
        scan must not re-credit the same ``![x](assets/arch.png)``
        destination as a bundled path mention.

        Reference-style images (``![a][ref]``) resolve through
        reference definitions whose destination line may lack a
        ``has_dest_span``; those definition lines are blanked entirely
        so the destination path cannot leak through.
        """
        image_hrefs: set = set()
        spans = []
        for link in cf.markdown.links():
            if not link.is_image:
                continue
            if link.has_dest_span:
                spans.append((link.dest_body_line, link.dest_col_start, link.dest_col_end))
            image_hrefs.add(link.href)
        ref_def_lines: set = set()
        if image_hrefs:
            for ref_def in cf.markdown.reference_definitions():
                if ref_def.href in image_hrefs:
                    for ln in range(ref_def.body_line_start, ref_def.body_line_end + 1):
                        ref_def_lines.add(ln)
        if not spans and not ref_def_lines:
            return body
        lines = body.split("\n")
        for line_no, start, end in spans:
            idx = line_no - 1
            if 0 <= idx < len(lines):
                line = lines[idx]
                lines[idx] = line[:start] + " " * (end - start) + line[end:]
        for line_no in ref_def_lines:
            idx = line_no - 1
            if 0 <= idx < len(lines):
                lines[idx] = " " * len(lines[idx])
        return "\n".join(lines)

    @staticmethod
    def _mask_html_comments(cf: ContentBlock, body: str) -> str:
        """*body* with HTML comment spans blanked out.

        A commented-out path (``<!-- old: scripts/deploy.py -->``) is not
        a visible disclosure reference; the raw-body mention scan must
        not credit it.
        """
        comments = cf.markdown.html_comments()
        if not comments:
            return body
        lines = body.split("\n")
        for comment in comments:
            for line_no in range(comment.body_line_start, comment.body_line_end + 1):
                idx = line_no - 1
                if 0 <= idx < len(lines):
                    lines[idx] = " " * len(lines[idx])
        return "\n".join(lines)

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

        Hidden entries, symlinks, nested skills, packaging scaffolding
        (SKILL.md, README.md, licenses), and test/eval scaffolding
        (``evals/``, ``tests/``, ``test_*.py``, ``testdata/`` — the same
        exclusions as agentskill-unreferenced-files) are skipped: those
        files are consumed by external harnesses, not loaded on demand
        as skill procedure.  Extensionless files (``scripts/deploy``)
        stay matchable by relative path, but only names carrying an
        extension become bare-name candidates — a mention of "deploy"
        alone is a word, not unambiguously a file.
        """
        rel_paths: Set[str] = set()
        names: Set[str] = set()
        try:
            for dirpath, dirnames, filenames in os.walk(skill_dir):
                base = Path(dirpath)
                at_root = base == skill_dir
                # Same nested-skill predicate as discovery: a subdirectory
                # with a mis-cased skill.md is not a nested skill, so its
                # files stay in this inventory on every filesystem.
                dirnames[:] = sorted(
                    d
                    for d in dirnames
                    if not d.startswith(".")
                    and d != "testdata"
                    and not (at_root and d in ("evals", "tests"))
                    and not (base / d).is_symlink()
                    and not exact_name_exists(base / d, "SKILL.md")
                )
                for name in filenames:
                    if name.startswith("."):
                        continue
                    if name in _SCAFFOLDING_NAMES or name.startswith(_SCAFFOLDING_PREFIXES):
                        continue
                    if name.startswith("test_") and name.endswith(".py"):
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

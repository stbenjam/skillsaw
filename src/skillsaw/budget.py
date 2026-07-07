"""
Context-window budget report.

Prices a repository's agent content in estimated context-window tokens,
split by *when* the content is paid for:

- **Session start** — content a coding agent loads into every session:
  instruction files (CLAUDE.md, AGENTS.md, GEMINI.md, copilot
  instructions, cline/kiro rules), rules-directory files without a
  ``paths:`` scope, ``alwaysApply`` cursor rules, and the frontmatter
  descriptions of skills, commands, and agents (harnesses list name +
  description in the system prompt so the agent knows what it can
  invoke; entries marked ``disable-model-invocation: true`` are not
  listed and are excluded).
- **On demand** — content loaded only when invoked or when its path
  scope matches: whole skill, command, and agent files, skill
  references, prompts, chatmodes, extra content files, path-scoped
  rules (``paths:`` frontmatter), ``applyTo``-scoped instruction files,
  and non-``alwaysApply`` cursor rules. Content-block categories
  contributed by skillsaw plugins land here too — pricing them beats
  dropping them, and their harness semantics are unknown.

``@``-import references in CLAUDE.md/AGENTS.md/GEMINI.md are resolved
transitively (four hops, relative to the importing file, repo-contained)
and billed as session-start items attributed to the importing harness.

No single harness reads every root instruction file, so the union
session total overstates any one session. ``by_harness`` carries
per-harness truth, and ``harness=...`` narrows the report to one.

The report prices the repository's content *as if installed and
active*: a marketplace's plugin rules and command descriptions are
billed to the sessions of users who install it. Imported files carry
no limit status — the ``context-budget`` rule never sees them, and
budget does not flag what lint cannot report.

Token counts are the same estimate the ``context-budget`` rule uses
(``len(text) // 4``) over the raw file, and every item is checked against
that rule's configured limits so the report and the enforcement agree.
Frontmatter is deliberately included in a file's on-demand cost even
though descriptions are also billed in session-start metadata: the rule
measures whole files for its per-file limits, and pricing them any other
way would let the report call an item "ok" that lint flags over budget.
The report never fails a run — ``skillsaw context`` observes, the
``context-budget`` rule enforces.

CodeRabbit and promptfoo content is excluded: skillsaw lints it as prose,
but it is consumed by those tools, not loaded into an agent's session.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from .utils import read_text

if TYPE_CHECKING:  # pragma: no cover
    from .context import RepositoryContext

# ContentBlock categories that are injected into every session (unless
# the individual file opts out via paths:/alwaysApply frontmatter).
SESSION_CATEGORIES = {"claude-md", "agents-md", "gemini-md", "instruction", "rule"}

# ContentBlock categories loaded only when the component is invoked.
ON_DEMAND_CATEGORIES = {
    "skill",
    "skill-ref",
    "command",
    "agent",
    "prompt",
    "chatmode",
    "context",
    "extra",
}

# Linted as prose, but consumed by CodeRabbit / promptfoo — never loaded
# into an agent session.
EXCLUDED_CATEGORIES = {"coderabbit", "promptfoo-prompt"}

_TRUTHY = (True, "true", "True")

DEFAULT_WINDOW = 200_000

# Which harness loads which session-start file. No harness reads every root
# instruction file, so a union total overstates any single session; the
# --harness option (or the by-harness breakdown) gives per-harness truth.
# Doc-verified (July 2026): Claude Code reads CLAUDE.md only (AGENTS.md via
# @-import when authors add one); Gemini CLI accepts GEMINI.md or AGENTS.md;
# Copilot reads copilot-instructions.md, *.instructions.md, and AGENTS.md;
# Cursor reads .cursor/rules and AGENTS.md. "default" is a generic
# AGENTS.md-reading agent (Codex, opencode, ...).
HARNESSES = ("claude", "cursor", "copilot", "gemini", "default")
# Gemini CLI's default context filename is GEMINI.md; AGENTS.md serves a
# gemini session only when no GEMINI.md exists (compute_budget strips the
# gemini attribution from AGENTS.md when GEMINI.md is present).
_AGENTS_MD_READERS = frozenset({"default", "gemini", "copilot", "cursor"})

# Claude Code resolves @-imports recursively with a maximum depth of four
# hops, relative to the importing file's directory, and they work anywhere
# in the file ("See @README for ..."), not only at line start (memory docs).
# This deliberately diverges from the instruction-imports-valid rule, which
# only validates line-start imports against the repo root.
_MAX_IMPORT_DEPTH = 4
_IMPORT_ANYWHERE_RE = re.compile(r"(?:^|(?<=\s))@([^\s@]+)")

# applyTo globs that mean "applies everywhere" — such files are effectively
# unconditional session content, not path-scoped.
_ALWAYS_GLOBS = {"**", "**/*"}


@dataclass
class BudgetItem:
    label: str
    category: str
    tokens: int
    path: Optional[str] = None  # repo-relative, None for aggregate rows
    status: Optional[str] = None  # "ok" | "warn" | "error" | None (no limit)
    via: Optional[str] = None  # repo-relative importer, for @-imported files
    harnesses: frozenset = frozenset()  # which harnesses load this at session start

    def to_dict(self) -> dict:
        d: Dict[str, Any] = {
            "label": self.label,
            "category": self.category,
            "tokens": self.tokens,
        }
        if self.path is not None:
            d["path"] = self.path
        if self.status is not None:
            d["status"] = self.status
        if self.via is not None:
            d["via"] = self.via
        if self.harnesses:
            d["harnesses"] = sorted(self.harnesses)
        return d


@dataclass
class MetadataGroup:
    """Frontmatter descriptions of one component kind (skill/command/agent).

    ``harnesses``: which harnesses list this kind in the system prompt.
    Skills (agentskills.io) are cross-tool; slash commands and subagents
    are Claude Code machinery.
    """

    kind: str
    harnesses: frozenset = frozenset()
    items: List[BudgetItem] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(i.tokens for i in self.items)


@dataclass
class BudgetReport:
    root: str
    window: int
    harness: str = "all"
    session_files: List[BudgetItem] = field(default_factory=list)
    metadata: List[MetadataGroup] = field(default_factory=list)
    on_demand: List[BudgetItem] = field(default_factory=list)
    limits: Dict[str, Tuple[Optional[int], Optional[int]]] = field(default_factory=dict)
    # Per-harness session totals, computed over the FULL (unfiltered) session
    # set — meaningful even when a --harness filter narrowed session_files.
    by_harness: Dict[str, int] = field(default_factory=dict)

    @property
    def session_total(self) -> int:
        return sum(i.tokens for i in self.session_files) + sum(g.total for g in self.metadata)

    @property
    def on_demand_total(self) -> int:
        return sum(i.tokens for i in self.on_demand)

    @property
    def window_percent(self) -> float:
        if self.window <= 0:
            return 0.0
        return self.session_total / self.window * 100

    def over_limit(self) -> List[BudgetItem]:
        """Every item whose status is warn or error, report-wide."""
        items = list(self.session_files) + list(self.on_demand)
        for group in self.metadata:
            items.extend(group.items)
        return [i for i in items if i.status in ("warn", "error")]

    def to_dict(self) -> dict:
        return {
            "root": self.root,
            "window": self.window,
            "harness": self.harness,
            "session_start": {
                "by_harness": self.by_harness,
                "files": [i.to_dict() for i in self.session_files],
                "metadata": {
                    f"{g.kind}s": {
                        "count": len(g.items),
                        "tokens": g.total,
                        "harnesses": sorted(g.harnesses),
                        "items": [i.to_dict() for i in g.items],
                    }
                    for g in self.metadata
                },
                "total_tokens": self.session_total,
                "window_percent": round(self.window_percent, 2),
            },
            "on_demand": {
                "files": [i.to_dict() for i in self.on_demand],
                "total_tokens": self.on_demand_total,
            },
            "limits": {
                category: {"warn": warn, "error": error}
                for category, (warn, error) in sorted(self.limits.items())
            },
        }


def _estimate_tokens(text: str) -> int:
    # Same estimator as the context-budget rule, so report and enforcement
    # never disagree on a number.
    return len(text) // 4


def _status(tokens: int, limits: Tuple[Optional[int], Optional[int]]) -> Optional[str]:
    warn, error = limits
    if error is not None and tokens > error:
        return "error"
    if warn is not None and tokens > warn:
        return "warn"
    if warn is not None or error is not None:
        return "ok"
    return None


def _rel(path: Path, root: Path) -> str:
    # Prefer the unresolved path: a symlink inside the repo pointing at a
    # target outside it should keep its repo-relative name, not leak the
    # target's absolute path.
    for candidate in (path, path.resolve()):
        try:
            return str(candidate.relative_to(root))
        except ValueError:
            continue
    return str(path)


def _scope_globs(value) -> Optional[List[str]]:
    """Normalize an applyTo/paths frontmatter value to a list of globs."""
    if isinstance(value, str) and value.strip():
        return [t.strip().strip("'\"") for t in value.split(",") if t.strip()]
    if isinstance(value, (list, tuple)) and value:
        return [str(t).strip().strip("'\"") for t in value]
    return None


def _frontmatter_fields(path: Path) -> Dict[str, Any]:
    """Lower-cased frontmatter key -> value for a plain instruction file.

    The lint tree models these as plain files, so peek through the shared
    frontmatter parser. Keys are lower-cased because real repos write
    ``applyTo``/``applyto`` interchangeably.
    """
    from .blocks import FrontmatteredBlock, FrontmatterField

    block = FrontmatteredBlock(path=path)
    if not block.has_frontmatter:
        return {}
    return {f.name.lower(): f.value for f in block.find(FrontmatterField)}


def _plain_instruction_always(path: Path) -> bool:
    """Whether a plain instruction file loads unconditionally at launch.

    - Kiro steering: ``inclusion: fileMatch``/``manual`` are conditional.
    - ``applyTo``/``paths`` globs narrower than ``**`` are path-scoped.
    - A ``*.instructions.md`` file with no ``applyTo`` at all is not
      applied automatically (VS Code docs) — conditional.
    """
    fields = _frontmatter_fields(path)
    inclusion = fields.get("inclusion")
    if isinstance(inclusion, str) and inclusion.strip().lower() in ("filematch", "manual"):
        return False
    globs = _scope_globs(fields.get("applyto"))
    if globs is None:
        globs = _scope_globs(fields.get("paths"))
    if globs is not None:
        return any(g in _ALWAYS_GLOBS for g in globs)
    if path.name.endswith(".instructions.md"):
        return False
    return True


def _always_loaded(block) -> bool:
    """Whether a session-category block really is unconditional.

    Rules-directory files with a ``paths:`` frontmatter key, scoped
    ``*.instructions.md`` files, and kiro fileMatch/manual steering are
    loaded when matching files are touched, not at launch; cursor
    ``.mdc`` rules are only injected whole when ``alwaysApply`` is true.
    Root CLAUDE.md/AGENTS.md/GEMINI.md are always session content —
    stray frontmatter on them never reroutes the file.
    """
    field_value = getattr(block.parent, "field_value", None)
    if field_value is not None:
        if block.category == "rule":
            return not field_value("paths")
        if block.path.suffix == ".mdc":
            return field_value("alwaysApply") in _TRUTHY
        return True
    if block.category != "instruction":
        return True
    return _plain_instruction_always(block.path)


def _harnesses_for(block) -> frozenset:
    """Which harnesses load this session-category block at session start."""
    category = block.category
    if category == "claude-md":
        return frozenset({"claude"})
    if category == "agents-md":
        return _AGENTS_MD_READERS
    if category == "gemini-md":
        return frozenset({"gemini"})
    if category == "rule":
        return frozenset({"claude"})
    name = block.path.name
    if name == "copilot-instructions.md" or name.endswith(".instructions.md"):
        return frozenset({"copilot"})
    if name == ".cursorrules" or block.path.suffix == ".mdc":
        return frozenset({"cursor"})
    # cline / windsurf / kiro and unknown instruction files: counted in the
    # union report only — none of the selectable harnesses loads them.
    return frozenset()


def compute_budget(
    context: "RepositoryContext",
    user_limits: Optional[Dict[str, Any]] = None,
    window: int = DEFAULT_WINDOW,
    harness: str = "all",
) -> BudgetReport:
    """Build a :class:`BudgetReport` from the repository's lint tree.

    ``user_limits`` is the raw ``limits`` mapping from the
    ``context-budget`` rule's config (category -> int or {warn, error});
    it is merged over that rule's defaults so the report reflects the
    same thresholds a lint run would enforce.

    ``harness`` narrows the session-start section to the files one
    harness actually loads (see :data:`HARNESSES`); ``"all"`` reports
    the union with per-harness totals in ``by_harness``. The on-demand
    section is never filtered — it is a per-invocation price list, not
    a sum.
    """
    # Late import: core modules must not import rule packages at module
    # import time (see tests/test_module_layering.py). The limit defaults
    # and parse semantics stay single-sourced in the rule.
    from .rules.builtin.context_budget.budget import DEFAULT_LIMITS, _parse_limit

    merged: Dict[str, Any] = dict(DEFAULT_LIMITS)
    if isinstance(user_limits, dict):
        merged.update(user_limits)
    limits = {}
    for category, value in merged.items():
        try:
            limits[category] = _parse_limit(value)
        except (TypeError, ValueError):
            # Malformed config entry: fall back to the default threshold
            # rather than crashing a report. Lint surfaces the config error.
            default = DEFAULT_LIMITS.get(category)
            limits[category] = _parse_limit(default) if default is not None else (None, None)

    if harness != "all" and harness not in HARNESSES:
        raise ValueError(f"Unknown harness {harness!r}; choose one of: all, {', '.join(HARNESSES)}")

    root = context.root_path
    report = BudgetReport(root=str(root), window=window, harness=harness, limits=limits)

    seen: set = set()
    session_by_resolved: Dict[Path, BudgetItem] = {}
    for block in context.lint_tree.content_blocks():
        category = block.category
        if category in EXCLUDED_CATEGORIES:
            continue
        if category in SESSION_CATEGORIES and _always_loaded(block):
            bucket = report.session_files
            harnesses = _harnesses_for(block)
        else:
            # On-demand categories, path-scoped/conditional session files,
            # and plugin-contributed categories we can't classify — pricing
            # unknowns as on-demand beats silently dropping them.
            bucket = report.on_demand
            harnesses = frozenset()

        resolved = block.path.resolve()
        if resolved in seen:
            # The docs-recommended `ln -s AGENTS.md CLAUDE.md` layout: one
            # file, two names. Don't double-bill, but the second name's
            # harnesses still load it — union them into the survivor.
            existing = session_by_resolved.get(resolved)
            if existing is not None and bucket is report.session_files:
                existing.harnesses = frozenset(existing.harnesses | harnesses)
            continue
        seen.add(resolved)

        raw = read_text(block.path)
        tokens = _estimate_tokens(raw) if raw is not None else block.estimate_tokens()
        item = BudgetItem(
            label=_rel(block.path, root),
            category=category,
            tokens=tokens,
            path=_rel(block.path, root),
            status=_status(tokens, limits.get(category, (None, None))),
            harnesses=harnesses,
        )
        bucket.append(item)
        if bucket is report.session_files:
            session_by_resolved[resolved] = item
        elif block.path.suffix == ".mdc":
            # Cursor injects a non-alwaysApply rule's *description* into
            # every session so the agent can request the rule — that
            # metadata is session cost even though the body loads later.
            desc = block.parent.field_value("description") if block.parent else None
            if isinstance(desc, str) and desc.strip():
                report.session_files.append(
                    BudgetItem(
                        label=f"{item.label} (description)",
                        category="cursor-rule-description",
                        tokens=_estimate_tokens(desc),
                        path=item.path,
                        harnesses=frozenset({"cursor"}),
                    )
                )

    # Symlinked root files (`ln -s AGENTS.md CLAUDE.md`, per the Claude Code
    # memory docs) collapse to a single lint-tree block, losing the other
    # name's attribution — union every root name that exists on disk into
    # whichever session item holds the shared resolved path.
    for name, name_harnesses in (
        ("CLAUDE.md", frozenset({"claude"})),
        ("AGENTS.md", _AGENTS_MD_READERS),
        ("GEMINI.md", frozenset({"gemini"})),
    ):
        candidate = root / name
        if candidate.is_file():
            existing = session_by_resolved.get(candidate.resolve())
            if existing is not None:
                existing.harnesses = frozenset(existing.harnesses | name_harnesses)

    _add_claude_only_files(report, root, seen)

    # Gemini CLI's default context file is GEMINI.md; AGENTS.md only serves
    # a gemini session when no GEMINI.md exists.
    if any(i.category == "gemini-md" for i in report.session_files):
        for item in report.session_files:
            if item.category == "agents-md":
                item.harnesses = frozenset(item.harnesses - {"gemini"})

    _add_imports(report, root)
    report.metadata = _gather_metadata(context, limits, root)

    for h in HARNESSES:
        total = sum(i.tokens for i in report.session_files if h in i.harnesses)
        total += sum(g.total for g in report.metadata if h in g.harnesses)
        if total > 0:
            report.by_harness[h] = total

    if harness != "all":
        report.session_files = [i for i in report.session_files if harness in i.harnesses]
        report.metadata = [g for g in report.metadata if harness in g.harnesses]

    report.session_files.sort(key=lambda i: (-i.tokens, i.label))
    report.on_demand.sort(key=lambda i: (-i.tokens, i.label))
    return report


def _add_claude_only_files(report: BudgetReport, root: Path, seen: set) -> None:
    """Bill .claude/CLAUDE.md and CLAUDE.local.md — both load into every
    Claude Code session but neither enters the lint tree, so the block
    loop never sees them. They get no limit status: the context-budget
    rule cannot see them either, and budget must not flag what lint
    cannot report."""
    for extra in (root / ".claude" / "CLAUDE.md", root / "CLAUDE.local.md"):
        if not extra.is_file():
            continue
        resolved = extra.resolve()
        if resolved in seen:
            continue
        raw = read_text(extra)
        if raw is None:
            continue
        seen.add(resolved)
        report.session_files.append(
            BudgetItem(
                label=_rel(extra, root),
                category="claude-md",
                tokens=_estimate_tokens(raw),
                path=_rel(extra, root),
                harnesses=frozenset({"claude"}),
            )
        )


# Root instruction files whose @-import references pull other files into the
# session (the same set the instruction-imports-valid rule scans).
_IMPORT_CATEGORIES = {"claude-md", "agents-md", "gemini-md"}


def _add_imports(report: BudgetReport, root: Path) -> None:
    """Resolve @-imports transitively and bill them as session-start items.

    Claude Code semantics: paths resolve relative to the importing file,
    imports work anywhere in a prose line, recursion is capped at four
    hops, ``@~/...`` home imports and paths escaping the repository are
    skipped. An import that lands on a file already billed in the session
    section is not double-billed — the importer's harnesses are unioned in
    (so ``CLAUDE.md`` importing ``@AGENTS.md`` attributes AGENTS.md to the
    claude session), and the union re-propagates through that file's own
    imports. A target that is an on-demand asset (a skill reference, say)
    gets a session import item too: the file plays both roles, and the two
    sections are never summed together.
    """
    from .markdown_doc import MarkdownDoc

    items_by_path = {(root / i.path).resolve(): i for i in report.session_files if i.path}
    queue = [
        ((root / item.path).resolve(), item, 0)
        for item in list(report.session_files)
        if item.category in _IMPORT_CATEGORIES
    ]
    # Re-traverse a file when new harnesses reach it, so a second root's
    # attribution propagates to transitive imports; harness sets only ever
    # grow, so this terminates.
    traversed_with: Dict[Path, frozenset] = {}
    while queue:
        src, src_item, depth = queue.pop(0)
        if depth >= _MAX_IMPORT_DEPTH:
            continue
        already = traversed_with.get(src, frozenset())
        if src_item.harnesses and src_item.harnesses <= already:
            continue
        if not src_item.harnesses and src in traversed_with:
            continue
        traversed_with[src] = already | src_item.harnesses
        text = read_text(src)
        if text is None:
            continue
        for _, line in MarkdownDoc(text).prose_lines():
            for match in _IMPORT_ANYWHERE_RE.finditer(line):
                ref = match.group(1)
                if ref.startswith("~"):
                    continue
                target = (src.parent / ref).resolve()
                try:
                    target.relative_to(root)
                except ValueError:
                    continue
                if not target.is_file():
                    continue
                existing = items_by_path.get(target)
                if existing is not None:
                    existing.harnesses = frozenset(existing.harnesses | src_item.harnesses)
                    queue.append((target, existing, depth + 1))
                    continue
                raw = read_text(target)
                if raw is None:
                    continue
                item = BudgetItem(
                    label=_rel(target, root),
                    category="import",
                    tokens=_estimate_tokens(raw),
                    path=_rel(target, root),
                    via=_rel(src, root),
                    harnesses=src_item.harnesses,
                )
                report.session_files.append(item)
                items_by_path[target] = item
                queue.append((target, item, depth + 1))


def _gather_metadata(
    context: "RepositoryContext",
    limits: Dict[str, Tuple[Optional[int], Optional[int]]],
    root: Path,
) -> List[MetadataGroup]:
    """Frontmatter descriptions — the metadata every session pays for so
    the agent knows which skills/commands/agents it can invoke."""
    from .blocks import AgentBlock, CommandBlock, SkillBlock

    kinds = [
        # Skills are the cross-tool agentskills.io standard; slash-command
        # and subagent descriptions are Claude Code machinery.
        ("skill", SkillBlock, "skill-description", frozenset({"claude", "default"})),
        ("command", CommandBlock, "command-description", frozenset({"claude"})),
        # The context-budget rule enforces no agent-description limit, so
        # budget must never flag one (limit_key None -> status always None).
        ("agent", AgentBlock, None, frozenset({"claude"})),
    ]

    groups: List[MetadataGroup] = []
    for kind, block_type, limit_key, kind_harnesses in kinds:
        group = MetadataGroup(kind=kind, harnesses=kind_harnesses)
        for block in context.lint_tree.find(block_type):
            if block.field_value("disable-model-invocation") in _TRUTHY:
                # Not listed in the model's context; the body still costs
                # on-demand tokens when the user invokes it.
                continue
            name = block.field_value("name")
            if not isinstance(name, str) or not name:
                # Skills are named by their directory, commands/agents by
                # their file stem when frontmatter omits a name.
                name = block.path.parent.name if kind == "skill" else block.path.stem
            desc = block.field_value("description")
            tokens = _estimate_tokens(desc) if isinstance(desc, str) else 0
            group.items.append(
                BudgetItem(
                    label=name,
                    category=limit_key or f"{kind}-description",
                    tokens=tokens,
                    path=_rel(block.path, root),
                    status=(
                        _status(tokens, limits.get(limit_key, (None, None)))
                        if limit_key is not None
                        else None
                    ),
                )
            )
        group.items.sort(key=lambda i: (-i.tokens, i.label))
        if group.items:
            groups.append(group)
    return groups

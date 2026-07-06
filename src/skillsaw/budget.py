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
  rules (``paths:`` frontmatter), and non-``alwaysApply`` cursor rules.
  Content-block categories contributed by skillsaw plugins land here
  too — pricing them beats dropping them, and their harness semantics
  are unknown.

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


@dataclass
class BudgetItem:
    label: str
    category: str
    tokens: int
    path: Optional[str] = None  # repo-relative, None for aggregate rows
    status: Optional[str] = None  # "ok" | "warn" | "error" | None (no limit)

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
        return d


@dataclass
class MetadataGroup:
    """Frontmatter descriptions of one component kind (skill/command/agent)."""

    kind: str
    items: List[BudgetItem] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(i.tokens for i in self.items)


@dataclass
class BudgetReport:
    root: str
    window: int
    session_files: List[BudgetItem] = field(default_factory=list)
    metadata: List[MetadataGroup] = field(default_factory=list)
    on_demand: List[BudgetItem] = field(default_factory=list)
    limits: Dict[str, Tuple[Optional[int], Optional[int]]] = field(default_factory=dict)

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
            "session_start": {
                "files": [i.to_dict() for i in self.session_files],
                "metadata": {
                    f"{g.kind}s": {
                        "count": len(g.items),
                        "tokens": g.total,
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


def _always_loaded(block) -> bool:
    """Whether a session-category block really is unconditional.

    Rules-directory files with a ``paths:`` frontmatter key are loaded
    when matching files are read, not at launch; cursor ``.mdc`` rules
    are only injected unconditionally when ``alwaysApply`` is true.
    """
    field_value = getattr(block.parent, "field_value", None)
    if field_value is None:
        return True  # plain instruction file, no frontmatter routing
    if block.category == "rule":
        return not field_value("paths")
    if block.path.suffix == ".mdc":
        return field_value("alwaysApply") in _TRUTHY
    return True


def compute_budget(
    context: "RepositoryContext",
    user_limits: Optional[Dict[str, Any]] = None,
    window: int = DEFAULT_WINDOW,
) -> BudgetReport:
    """Build a :class:`BudgetReport` from the repository's lint tree.

    ``user_limits`` is the raw ``limits`` mapping from the
    ``context-budget`` rule's config (category -> int or {warn, error});
    it is merged over that rule's defaults so the report reflects the
    same thresholds a lint run would enforce.
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

    root = context.root_path
    report = BudgetReport(root=str(root), window=window, limits=limits)

    seen: set = set()
    for block in context.lint_tree.content_blocks():
        category = block.category
        if category in EXCLUDED_CATEGORIES:
            continue
        if category in SESSION_CATEGORIES and _always_loaded(block):
            bucket = report.session_files
        else:
            # On-demand categories, path-scoped/conditional session files,
            # and plugin-contributed categories we can't classify — pricing
            # unknowns as on-demand beats silently dropping them.
            bucket = report.on_demand

        resolved = block.path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)

        raw = read_text(block.path)
        tokens = _estimate_tokens(raw) if raw is not None else block.estimate_tokens()
        bucket.append(
            BudgetItem(
                label=_rel(block.path, root),
                category=category,
                tokens=tokens,
                path=_rel(block.path, root),
                status=_status(tokens, limits.get(category, (None, None))),
            )
        )

    report.metadata = _gather_metadata(context, limits, root)

    report.session_files.sort(key=lambda i: (-i.tokens, i.label))
    report.on_demand.sort(key=lambda i: (-i.tokens, i.label))
    return report


def _gather_metadata(
    context: "RepositoryContext",
    limits: Dict[str, Tuple[Optional[int], Optional[int]]],
    root: Path,
) -> List[MetadataGroup]:
    """Frontmatter descriptions — the metadata every session pays for so
    the agent knows which skills/commands/agents it can invoke."""
    from .blocks import AgentBlock, CommandBlock, SkillBlock

    kinds = [
        ("skill", SkillBlock, "skill-description"),
        ("command", CommandBlock, "command-description"),
        # The context-budget rule enforces no agent-description limit, so
        # budget must never flag one (limit_key None -> status always None).
        ("agent", AgentBlock, None),
    ]

    groups: List[MetadataGroup] = []
    for kind, block_type, limit_key in kinds:
        group = MetadataGroup(kind=kind)
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

"""Handler for the ``skillsaw badge`` subcommand."""

from __future__ import annotations

import sys
from pathlib import Path

from ..context import RepositoryContext
from ..linter import Linter
from ._config import load_config
from ._helpers import _RuleProgress, _ansi_colors, color_enabled

_BADGE_FILENAME = ".skillsaw-badge.json"
_CARD_FILENAME = ".skillsaw-card.svg"


def _git(root_path: Path, *argv):
    """Run git in *root_path*, returning stripped stdout or None on failure."""
    import subprocess

    try:
        result = subprocess.run(
            ["git", "-C", str(root_path), *argv],
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _repo_display_name(root_path: Path) -> str:
    """Repository name shown on the report card.

    Prefers the origin remote's repository basename — checkout directory
    names vary (forks, CI workspaces, worktrees) while the remote does
    not — and falls back to the directory name.
    """
    remote = _git(root_path, "remote", "get-url", "origin")
    if remote:
        name = remote.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1]
        if name.endswith(".git"):
            name = name[: -len(".git")]
        if name:
            return name
    return root_path.resolve().name


def _github_raw_url(root_path: Path, badge_path: Path):
    """Best-effort raw.githubusercontent.com URL for the badge file.

    Returns None when the repo has no recognizable GitHub remote.
    """
    import re

    remote = _git(root_path, "config", "--get", "remote.origin.url")
    if not remote:
        return None
    m = re.search(r"github\.com[:/]([^/]+)/(.+?)(?:\.git)?/?$", remote)
    if not m:
        return None
    owner, repo = m.group(1), m.group(2)

    branch = _git(root_path, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if branch and branch.startswith("origin/"):
        branch = branch[len("origin/") :]
    if not branch:
        branch = _git(root_path, "rev-parse", "--abbrev-ref", "HEAD") or "main"

    try:
        rel = badge_path.resolve().relative_to(root_path.resolve())
    except ValueError:
        rel = Path(badge_path.name)
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{rel.as_posix()}"


def _run_badge(args):
    import json
    from urllib.parse import quote

    if not args.path.exists():
        print(f"Error: Path not found: {args.path}", file=sys.stderr)
        sys.exit(1)

    context = RepositoryContext(args.path)
    config, _config_path = load_config(args, args.path)

    try:
        linter = Linter(context, config)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    rule_progress = _RuleProgress(args)
    try:
        violations = linter.run(progress=rule_progress)
    finally:
        rule_progress.clear()

    from ..grade import compute_grade

    content_tokens = sum(b.estimate_tokens() for b in context.lint_tree.content_blocks())
    grade = compute_grade(violations, content_tokens)

    badge_path = args.output or (context.root_path / _BADGE_FILENAME)
    badge_path.parent.mkdir(parents=True, exist_ok=True)
    # Both artifacts are committed and regenerated in CI, so they must be
    # byte-identical across operating systems. Write bytes directly —
    # text mode without newline="" would CRLF-translate on Windows and
    # every regeneration there would churn the whole file.
    badge_path.write_bytes((json.dumps(grade.badge_json(), indent=2) + "\n").encode("utf-8"))

    card_path = None
    if getattr(args, "large", False):
        from collections import Counter

        from ..card import render_card
        from ..lint_target import PluginNode, SkillNode

        card_path = badge_path.parent / _CARD_FILENAME
        card_path.write_bytes(
            render_card(
                grade,
                repo_name=_repo_display_name(context.root_path),
                plugin_count=len(context.lint_tree.find(PluginNode)),
                skill_count=len(context.lint_tree.find(SkillNode)),
                top_rules=Counter(v.rule_id for v in violations).most_common(3),
                theme=getattr(args, "theme", "dark"),
            ).encode("utf-8")
        )

    c = _ansi_colors(color_enabled(sys.stdout, args.color))
    grade_color = (
        c["green"]
        if grade.letter[0] in "AB"
        else (c["yellow"] if grade.letter[0] == "C" else c["red"])
    )
    print(f"Grade: {grade_color}{c['bold']}{grade.letter}{c['reset']}")
    print(
        f"  {grade.errors} error(s), {grade.warnings} warning(s), {grade.info} info"
        f" across ~{grade.content_tokens:,} content tokens"
        f" ({grade.density:.2f} weighted violations per 10k tokens)"
    )
    print(f"\nBadge written to {badge_path}")
    if card_path is not None:
        print(f"Card written to {card_path}")
    else:
        print("Run `skillsaw badge --large` to generate a card-sized badge.")

    raw_url = _github_raw_url(context.root_path, badge_path)
    if raw_url is None:
        raw_url = "<RAW_URL_TO_YOUR_BADGE_JSON>"
        print(
            "\nNo GitHub remote detected — replace the URL placeholder after"
            " publishing the badge file somewhere shields.io can fetch it."
        )
    from ..grade import logo_data_uri

    encoded = quote(raw_url, safe="")
    label = "skillsaw"
    logo = quote(logo_data_uri(), safe="")

    print(f"\n{c['bold']}Markdown for your README:{c['reset']}")
    print(f"\n  Dynamic JSON badge (https://shields.io/badges/dynamic-json-badge):")
    print(
        f"  [![skillsaw grade](https://img.shields.io/badge/dynamic/json"
        f"?url={encoded}&query=%24.message&label={label}&color={grade.color}"
        f"&logo={logo})](https://skillsaw.org/)"
    )
    print(f"\n  Endpoint badge (color updates with the grade automatically):")
    print(
        f"  [![skillsaw grade](https://img.shields.io/endpoint?url={encoded})]"
        f"(https://skillsaw.org/)"
    )
    if card_path is None:
        print(
            f"\nCommit {badge_path.name} and regenerate it (e.g. in CI) whenever"
            " the repository changes."
        )
    else:
        card_url = _github_raw_url(context.root_path, card_path) or "<RAW_URL_TO_YOUR_CARD_SVG>"
        print("\n  Report card (self-contained SVG):")
        print(f"  [![skillsaw report card]({card_url})](https://skillsaw.org/)")
        print(
            f"\nCommit {badge_path.name} and {card_path.name} and regenerate them"
            " (e.g. in CI) whenever the repository changes."
        )
        print(
            "Note: GitHub's image proxy (camo) caches README images aggressively,"
            " so a regenerated card can appear stale for a while."
        )
    sys.exit(0)

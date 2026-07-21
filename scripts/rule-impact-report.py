#!/usr/bin/env python3
"""Build a markdown report of how a PR's changed rules affect real repos.

Inputs are two directories of ``skillsaw lint --format json`` outputs — one
produced with the PR's merge-base install, one with the PR's install — with
one ``<repo>.json`` per linted repository (same file names in both). Both
runs force exactly the rules the PR touches (``--rule``, which bypasses
version gating and repo-type auto-detection); the base/head *diff* then
isolates the PR's effect on each repo.

Prints markdown to stdout (leading with a marker comment so CI can find and
update a previous report), always exits 0. The phrase "No rule-impact
differences" is load-bearing: CI greps for it to decide whether a comment is
worth posting.
"""

import argparse
import json
from pathlib import Path
from urllib.parse import quote

MARKER = "<!-- rule-impact-report -->"
SAMPLE_LIMIT = 10


def load_results(directory):
    results = {}
    for path in sorted(Path(directory).glob("*.json")):
        try:
            results[path.stem] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            results[path.stem] = None
    return results


def load_shas(directory):
    """Map result-file stems to the commit each repo was linted at.

    One ``<stem>.sha`` file per repo, containing the clone's HEAD. Missing
    or malformed files simply drop the permalink for that repo — the report
    falls back to plain ``file:line`` text.
    """
    shas = {}
    if not directory:
        return shas
    for path in Path(directory).glob("*.sha"):
        sha = path.read_text(encoding="utf-8").strip()
        if sha and all(c in "0123456789abcdef" for c in sha.lower()):
            shas[path.stem] = sha
    return shas


def repo_label(stem, link=True):
    """Render a result-file stem as markdown.

    The workflow encodes ``org/repo`` as ``org__repo`` in file names; stems
    without the separator (e.g. hand-run local results) render as plain code.
    """
    if "__" not in stem:
        return f"`{stem}`"
    slug = stem.replace("__", "/")
    label = f"[{slug}](https://github.com/{slug})"
    return label if link else slug


def violation_keys(data):
    # message is part of the identity: two whole-file violations from the
    # same rule on the same file (both line=None) must not collapse.
    return {
        (v.get("rule_id", "?"), v.get("file_path", "?"), v.get("line"), v.get("message", "?"))
        for v in data.get("violations", [])
    }


def _sample_order(key):
    # line can be None (whole-file violations) or an int — never compare
    # them directly: sort None first within a (rule, file) group.
    rule_id, file_path, line, message = key
    return (rule_id, file_path, line is not None, line or 0, message)


def format_sample(keys, slug=None, sha=None):
    """Render sampled violation keys, linking each location to the exact
    file (and line) at the commit that was linted when the repo slug and
    SHA are known."""
    lines = []
    for rule_id, file_path, line, _message in sorted(keys, key=_sample_order)[:SAMPLE_LIMIT]:
        location = f"{file_path}:{line}" if line else file_path
        if slug and sha:
            url = f"https://github.com/{slug}/blob/{sha}/{quote(file_path.lstrip('./'))}"
            if line:
                url += f"#L{line}"
            location = f"[{location}]({url})"
        lines.append(f"- `{rule_id}` — {location}")
    if len(keys) > SAMPLE_LIMIT:
        lines.append(f"- … and {len(keys) - SAMPLE_LIMIT} more")
    return lines


def rule_counts(keys):
    counts = {}
    for rule_id, *_ in keys:
        counts[rule_id] = counts.get(rule_id, 0) + 1
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="Directory of merge-base JSON results")
    parser.add_argument("--head", required=True, help="Directory of PR-head JSON results")
    parser.add_argument(
        "--rules", default="", help="Space-separated rule ids the PR changed (for the header)"
    )
    parser.add_argument(
        "--shas",
        default=None,
        help="Directory of <repo>.sha files recording the commit each repo "
        "was linted at; findings link to the file at that commit",
    )
    args = parser.parse_args()

    base_results = load_results(args.base)
    head_results = load_results(args.head)
    shas = load_shas(args.shas)

    sections = []
    clean = []
    for repo in sorted(set(base_results) | set(head_results)):
        base = base_results.get(repo)
        head = head_results.get(repo)
        if base is None or head is None:
            which = " and ".join(
                side for side, data in (("base", base), ("head", head)) if data is None
            )
            sections.append(f"### {repo_label(repo)}\n\n⚠️ {which} run produced no parseable JSON.")
            continue

        new = violation_keys(head) - violation_keys(base)
        resolved = violation_keys(base) - violation_keys(head)
        if not new and not resolved:
            clean.append(repo)
            continue

        lines = [f"### {repo_label(repo)}", ""]
        summary = []
        if new:
            summary.append(f"**{len(new)} new**")
        if resolved:
            summary.append(f"{len(resolved)} resolved")
        by_rule = ", ".join(
            f"`{rule}` ×{count}" for rule, count in sorted(rule_counts(new | resolved).items())
        )
        lines.append(f"{' / '.join(summary)} ({by_rule})")
        slug = repo.replace("__", "/") if "__" in repo else None
        sha = shas.get(repo)
        if new:
            lines += ["", "New findings:"] + format_sample(new, slug=slug, sha=sha)
        if resolved:
            lines += ["", "Resolved:"] + format_sample(resolved, slug=slug, sha=sha)
        sections.append("\n".join(lines))

    print(MARKER)
    print("## Real-repo rule impact")
    print()
    rules = " ".join(f"`{r}`" for r in args.rules.split())
    print(
        f"This PR changes {rules or 'rule code'}. Those rules were force-run "
        "(`--rule`) against the integration-test repos with the PR head and "
        "its merge base — the differences below are what these repos would "
        "see once the rules reach them."
    )
    print()
    clean_list = ", ".join(repo_label(repo) for repo in clean)
    if sections:
        print("\n\n".join(sections))
        if clean:
            print()
            print(f"Also checked, no differences: {clean_list}.")
    else:
        print(f"**No rule-impact differences.** Checked: {clean_list}.")


if __name__ == "__main__":
    main()

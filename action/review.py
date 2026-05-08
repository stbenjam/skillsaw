"""Post skillsaw results as a GitHub PR review with inline comments."""

import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request

MARKER = "<!-- skillsaw-review -->"
FINGERPRINT_RE = re.compile(r"<!-- skillsaw:([a-f0-9]+) -->")
SEVERITY_ICONS = {"error": "❌", "warning": "⚠️", "info": "ℹ️"}
API = "https://api.github.com"


def github_api(method, path, body=None):
    token = os.environ["GITHUB_TOKEN"]
    url = f"{API}{path}" if path.startswith("/") else path
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            resp_body = resp.read().decode()
            return json.loads(resp_body) if resp_body else None
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        print(f"GitHub API error: {e.code} {e.reason}: {error_body}", file=sys.stderr)
        raise


def fingerprint(rule_id, file_path, message):
    key = f"{rule_id}:{file_path}:{message}"
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def get_diff_lines(repo, pr_number):
    """Get the set of (path, line) tuples for added/modified lines in the PR."""
    diff_lines = set()
    page = 1
    while True:
        files = github_api("GET", f"/repos/{repo}/pulls/{pr_number}/files?per_page=100&page={page}")
        if not files:
            break
        for f in files:
            path = f["filename"]
            patch = f.get("patch", "")
            if not patch:
                continue
            current_line = 0
            for line in patch.split("\n"):
                hunk = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
                if hunk:
                    current_line = int(hunk.group(1))
                    continue
                if line.startswith("+"):
                    diff_lines.add((path, current_line))
                    current_line += 1
                elif line.startswith("-"):
                    pass
                else:
                    current_line += 1
        page += 1
    return diff_lines


def sync_inline_comments(repo, pr_number, new_comments):
    """Diff existing skillsaw comments against new findings.

    Returns (to_post, live_review_ids) where to_post is the list of genuinely
    new comments and live_review_ids is the set of review IDs that still have
    active skillsaw comments (kept or with replies).
    """
    all_comments = github_api(
        "GET", f"/repos/{repo}/pulls/{pr_number}/comments?per_page=100"
    )
    if not all_comments:
        return new_comments, set()

    existing = {}
    for c in all_comments:
        m = FINGERPRINT_RE.search(c.get("body", ""))
        if m:
            existing[m.group(1)] = c

    if not existing:
        return new_comments, set()

    current_fps = {c["fingerprint"] for c in new_comments}

    replied_to = set()
    for c in all_comments:
        if c.get("in_reply_to_id"):
            replied_to.add(c["in_reply_to_id"])

    live_review_ids = set()
    deleted = 0
    preserved = 0
    for fp, comment in existing.items():
        if fp in current_fps:
            review_id = comment.get("pull_request_review_id")
            if review_id:
                live_review_ids.add(review_id)
        else:
            if comment["id"] in replied_to:
                preserved += 1
                review_id = comment.get("pull_request_review_id")
                if review_id:
                    live_review_ids.add(review_id)
                continue
            try:
                github_api("DELETE", f"/repos/{repo}/pulls/comments/{comment['id']}")
                deleted += 1
            except urllib.error.HTTPError:
                pass

    if deleted:
        print(f"Deleted {deleted} comment(s) for fixed issues.")
    if preserved:
        print(f"Preserved {preserved} comment(s) with replies.")

    to_post = [c for c in new_comments if c["fingerprint"] not in existing]
    return to_post, live_review_ids


def supersede_old_reviews(repo, pr_number, live_review_ids):
    """Mark previous skillsaw review bodies as superseded.

    Skips reviews that still have live inline comments.
    """
    reviews = github_api("GET", f"/repos/{repo}/pulls/{pr_number}/reviews?per_page=100")
    for review in reviews:
        body = review.get("body", "") or ""
        if MARKER in body and "superseded" not in body:
            if review["id"] in live_review_ids:
                continue
            try:
                github_api(
                    "PUT",
                    f"/repos/{repo}/pulls/{pr_number}/reviews/{review['id']}",
                    {"body": f"{MARKER}\n*Skillsaw review superseded by latest review below.*"},
                )
            except urllib.error.HTTPError:
                pass


def build_summary(report, inline_violations, body_violations):
    """Build the review body with summary and non-inline violations."""
    summary = report["summary"]
    lines = [MARKER, "## [skillsaw](https://github.com/stbenjam/skillsaw)\n"]

    total = summary["errors"] + summary["warnings"] + summary.get("info", 0)
    if total == 0:
        lines.append("**All checks passed** — no violations found.\n")
        return "\n".join(lines)

    if not body_violations:
        return "\n".join(lines)

    lines.append(
        f"| Errors | Warnings | Info |\n"
        f"|--------|----------|------|\n"
        f"| {summary['errors']} | {summary['warnings']} | {summary.get('info', 0)} |\n"
    )

    for v in body_violations:
        icon = SEVERITY_ICONS.get(v["severity"], "")
        loc = ""
        if v.get("file_path"):
            loc = f" `{v['file_path']}"
            if v.get("line"):
                loc += f":{v['line']}"
            loc += "`"
        lines.append(f"- {icon} **{v['severity']}**{loc}: {v['message']}")

    return "\n".join(lines)


def main():
    report_file = os.environ.get("SKILLSAW_REPORT_FILE", "")
    if not report_file or not os.path.exists(report_file):
        print("No skillsaw report found, skipping review.", file=sys.stderr)
        return

    with open(report_file) as f:
        content = f.read().strip()
    if not content:
        print("Report file is empty, skipping review.", file=sys.stderr)
        return
    try:
        report = json.loads(content)
    except json.JSONDecodeError as e:
        print(f"Failed to parse report JSON: {e}", file=sys.stderr)
        return

    repo = os.environ["GITHUB_REPOSITORY"]
    pr_number = os.environ["PR_NUMBER"]
    head_sha = os.environ["HEAD_SHA"]

    violations = report.get("violations", [])

    diff_lines = get_diff_lines(repo, pr_number)

    inline_violations = []
    body_violations = []
    for v in violations:
        path = v.get("file_path")
        line = v.get("line")
        if path and line and (path, line) in diff_lines:
            inline_violations.append(v)
        else:
            body_violations.append(v)

    new_comments = []
    for v in inline_violations:
        icon = SEVERITY_ICONS.get(v["severity"], "")
        fp = fingerprint(v["rule_id"], v["file_path"], v["message"])
        new_comments.append({
            "path": v["file_path"],
            "line": v["line"],
            "side": "RIGHT",
            "body": (
                f"{icon} **{v['severity']}** (`{v['rule_id']}`): {v['message']}\n"
                f"<!-- skillsaw:{fp} -->"
            ),
            "fingerprint": fp,
        })

    to_post, live_review_ids = sync_inline_comments(repo, pr_number, new_comments)

    supersede_old_reviews(repo, pr_number, live_review_ids)

    review_body = build_summary(report, inline_violations, body_violations)

    review_comments = [
        {k: v for k, v in c.items() if k != "fingerprint"}
        for c in to_post
    ]

    review = {
        "commit_id": head_sha,
        "body": review_body,
        "event": "COMMENT",
    }
    if review_comments:
        review["comments"] = review_comments

    github_api("POST", f"/repos/{repo}/pulls/{pr_number}/reviews", review)

    kept = len(new_comments) - len(to_post)
    print(
        f"Posted review: {len(review_comments)} new, {kept} unchanged, "
        f"{len(body_violations)} in body."
    )


if __name__ == "__main__":
    main()

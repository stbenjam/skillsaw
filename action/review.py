"""Post skillsaw results as individual GitHub PR comments."""

import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request

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


def sync_comments(repo, pr_number, new_comments):
    """Diff existing skillsaw comments against new findings.

    Returns to_post: the list of genuinely new comments to create.
    """
    all_comments = []
    page = 1
    while True:
        page_comments = github_api(
            "GET", f"/repos/{repo}/pulls/{pr_number}/comments?per_page=100&page={page}"
        )
        if not page_comments:
            break
        all_comments.extend(page_comments)
        page += 1

    existing = {}
    for c in all_comments:
        m = FINGERPRINT_RE.search(c.get("body", ""))
        if m:
            existing[m.group(1)] = c

    if not existing:
        return new_comments

    current_fps = {c["fingerprint"] for c in new_comments}

    replied_to = set()
    for c in all_comments:
        if c.get("in_reply_to_id"):
            replied_to.add(c["in_reply_to_id"])

    deleted = 0
    preserved = 0
    for fp, comment in existing.items():
        if fp not in current_fps:
            if comment["id"] in replied_to:
                preserved += 1
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

    return [c for c in new_comments if c["fingerprint"] not in existing]


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
    if not violations:
        print("No violations found.")
        return

    diff_lines = get_diff_lines(repo, pr_number)

    new_comments = []
    for v in violations:
        path = v.get("file_path")
        line = v.get("line")
        if not path:
            continue

        fp = fingerprint(v["rule_id"], path, v["message"])
        icon = SEVERITY_ICONS.get(v["severity"], "")
        body = (
            f"{icon} **{v['severity']}** (`{v['rule_id']}`): {v['message']}\n"
            f"<!-- skillsaw:{fp} -->"
        )

        comment = {"path": path, "commit_id": head_sha, "body": body, "fingerprint": fp}
        if line and (path, line) in diff_lines:
            comment["line"] = line
            comment["side"] = "RIGHT"
        else:
            comment["subject_type"] = "file"

        new_comments.append(comment)

    to_post = sync_comments(repo, pr_number, new_comments)

    posted = 0
    for comment in to_post:
        payload = {k: v for k, v in comment.items() if k != "fingerprint"}
        try:
            github_api("POST", f"/repos/{repo}/pulls/{pr_number}/comments", payload)
            posted += 1
        except urllib.error.HTTPError:
            pass

    kept = len(new_comments) - len(to_post)
    print(f"Posted {posted} new comment(s), {kept} unchanged.")


if __name__ == "__main__":
    main()

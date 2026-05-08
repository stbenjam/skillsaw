"""Post skillsaw results as a GitHub PR review with inline comments."""

import json
import os
import re
import sys
import urllib.error
import urllib.request

MARKER = "<!-- skillsaw-review -->"
SEVERITY_ICONS = {"error": "✗", "warning": "⚠️", "info": "ℹ️"}
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
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        print(f"GitHub API error: {e.code} {e.reason}: {error_body}", file=sys.stderr)
        raise


def graphql(query, variables=None):
    token = os.environ["GITHUB_TOKEN"]
    body = {"query": query}
    if variables:
        body["variables"] = variables
    return github_api("POST", "https://api.github.com/graphql", body)


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


def resolve_previous_reviews(repo, pr_number):
    """Resolve review threads from previous skillsaw reviews."""
    owner, name = repo.split("/")
    result = graphql(
        """
        query($owner: String!, $name: String!, $pr: Int!) {
          repository(owner: $owner, name: $name) {
            pullRequest(number: $pr) {
              reviews(first: 100) {
                nodes {
                  body
                  databaseId
                }
              }
              reviewThreads(first: 100) {
                nodes {
                  id
                  isResolved
                  comments(first: 1) {
                    nodes { body }
                  }
                }
              }
            }
          }
        }
        """,
        {"owner": owner, "name": name, "pr": int(pr_number)},
    )

    pr_data = result.get("data", {}).get("repository", {}).get("pullRequest", {})

    for review in pr_data.get("reviews", {}).get("nodes", []):
        body = review.get("body") or ""
        if MARKER in body:
            try:
                github_api(
                    "PUT",
                    f"/repos/{repo}/pulls/{pr_number}/reviews/{review['databaseId']}",
                    {"body": f"{MARKER}\n*Superseded by latest review below.*"},
                )
            except urllib.error.HTTPError:
                pass

    resolved_count = 0
    for thread in pr_data.get("reviewThreads", {}).get("nodes", []):
        if thread.get("isResolved"):
            continue
        first_comment = (thread.get("comments", {}).get("nodes") or [{}])[0]
        comment_body = first_comment.get("body", "")
        if any(sev in comment_body for sev in SEVERITY_ICONS.values()):
            try:
                graphql(
                    """
                    mutation($id: ID!) {
                      resolveReviewThread(input: {threadId: $id}) {
                        thread { isResolved }
                      }
                    }
                    """,
                    {"id": thread["id"]},
                )
                resolved_count += 1
            except Exception:
                pass

    if resolved_count:
        print(f"Resolved {resolved_count} previous review thread(s).")


def build_summary(report, inline_violations, body_violations):
    """Build the review body with summary and non-inline violations."""
    summary = report["summary"]
    lines = [MARKER, "## skillsaw\n"]

    total = summary["errors"] + summary["warnings"] + summary.get("info", 0)
    if total == 0:
        lines.append("**All checks passed** — no violations found.\n")
        return "\n".join(lines)

    lines.append(
        f"| Errors | Warnings | Info |\n"
        f"|--------|----------|------|\n"
        f"| {summary['errors']} | {summary['warnings']} | {summary.get('info', 0)} |\n"
    )

    if body_violations:
        lines.append("<details><summary>Violations outside changed lines</summary>\n")
        for v in body_violations:
            icon = SEVERITY_ICONS.get(v["severity"], "")
            loc = ""
            if v.get("file_path"):
                loc = f" `{v['file_path']}"
                if v.get("line"):
                    loc += f":{v['line']}"
                loc += "`"
            lines.append(f"- {icon} **{v['severity']}**{loc}: {v['message']}")
        lines.append("\n</details>")

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

    diff_files = {path for path, _ in diff_lines}

    inline_violations = []
    body_violations = []
    for v in violations:
        path = v.get("file_path")
        line = v.get("line")
        if path and line and (path, line) in diff_lines:
            inline_violations.append(v)
        elif path and path in diff_files:
            inline_violations.append(v)
        else:
            body_violations.append(v)

    resolve_previous_reviews(repo, pr_number)

    review_body = build_summary(report, inline_violations, body_violations)

    comments = []
    for v in inline_violations:
        icon = SEVERITY_ICONS.get(v["severity"], "")
        comment = {
            "path": v["file_path"],
            "body": f"{icon} **{v['severity']}** (`{v['rule_id']}`): {v['message']}",
        }
        if v.get("line"):
            comment["line"] = v["line"]
            comment["side"] = "RIGHT"
        else:
            comment["subject_type"] = "file"
        comments.append(comment)

    review = {
        "commit_id": head_sha,
        "body": review_body,
        "event": "COMMENT",
    }
    if comments:
        review["comments"] = comments

    github_api("POST", f"/repos/{repo}/pulls/{pr_number}/reviews", review)
    print(f"Posted review with {len(comments)} inline comment(s).")


if __name__ == "__main__":
    main()

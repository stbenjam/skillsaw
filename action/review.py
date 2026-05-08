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


def graphql(query, variables=None):
    token = os.environ["GITHUB_TOKEN"]
    body = {"query": query}
    if variables:
        body["variables"] = variables
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{API}/graphql",
        data=data,
        method="POST",
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read().decode())
    if result.get("errors"):
        print(f"GraphQL error: {result['errors']}", file=sys.stderr)
    return result


def get_review_threads(repo, pr_number):
    """Fetch all review threads and their first comment bodies."""
    owner, name = repo.split("/")
    threads = []
    cursor = None
    while True:
        variables = {"owner": owner, "repo": name, "pr": int(pr_number)}
        after_decl = ", $after: String" if cursor else ""
        after_arg = ", after: $after" if cursor else ""
        if cursor:
            variables["after"] = cursor
        result = graphql(
            """
            query($owner: String!, $repo: String!, $pr: Int!%s) {
                repository(owner: $owner, name: $repo) {
                    pullRequest(number: $pr) {
                        reviewThreads(first: 100%s) {
                            nodes {
                                id
                                isResolved
                                comments(first: 1) {
                                    nodes { body }
                                }
                            }
                            pageInfo { hasNextPage endCursor }
                        }
                    }
                }
            }
            """ % (after_decl, after_arg),
            variables,
        )
        pr_data = (result.get("data") or {}).get("repository", {}).get("pullRequest", {})
        thread_data = pr_data.get("reviewThreads", {})
        threads.extend(thread_data.get("nodes") or [])
        page_info = thread_data.get("pageInfo", {})
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info["endCursor"]
    return threads


def resolve_threads_by_fingerprints(repo, pr_number, fingerprints):
    """Resolve review threads whose comments match the given fingerprints."""
    if not fingerprints:
        return 0
    threads = get_review_threads(repo, pr_number)
    resolved = 0
    for thread in threads:
        if thread.get("isResolved"):
            continue
        comments = (thread.get("comments") or {}).get("nodes") or []
        if not comments:
            continue
        body = comments[0].get("body", "")
        m = FINGERPRINT_RE.search(body)
        if m and m.group(1) in fingerprints:
            result = graphql(
                """
                mutation($threadId: ID!) {
                    resolveReviewThread(input: {threadId: $threadId}) {
                        thread { isResolved }
                    }
                }
                """,
                {"threadId": thread["id"]},
            )
            if (
                (result.get("data") or {})
                .get("resolveReviewThread", {})
                .get("thread", {})
                .get("isResolved")
            ):
                resolved += 1
    return resolved


def fingerprint(rule_id, file_path, message):
    key = f"{rule_id}:{file_path}:{message}"
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def get_diff_info(repo, pr_number):
    """Get diff files and added/modified line numbers.

    Returns (diff_files, diff_lines) where diff_files is a set of file paths
    and diff_lines is a set of (path, line) tuples.
    """
    diff_files = set()
    diff_lines = set()
    page = 1
    while True:
        files = github_api("GET", f"/repos/{repo}/pulls/{pr_number}/files?per_page=100&page={page}")
        if not files:
            break
        for f in files:
            path = f["filename"]
            diff_files.add(path)
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
    return diff_files, diff_lines


def sync_comments(repo, pr_number, new_comments):
    """Diff existing skillsaw comments against new findings.

    Resolves threads for fixed violations, returns genuinely new comments.
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
    stale_fps = {fp for fp in existing if fp not in current_fps}

    if stale_fps:
        try:
            resolved = resolve_threads_by_fingerprints(repo, pr_number, stale_fps)
            if resolved:
                print(f"Resolved {resolved} thread(s) for fixed issues.")
        except Exception as e:
            print(f"Failed to resolve threads: {e}", file=sys.stderr)

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

    diff_files, diff_lines = get_diff_info(repo, pr_number)

    new_comments = []
    skipped = 0
    for v in violations:
        path = v.get("file_path")
        line = v.get("line")
        if not path:
            continue

        if path not in diff_files:
            skipped += 1
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

    if skipped:
        print(f"Skipped {skipped} violation(s) on files not in the diff.")

    try:
        to_post = sync_comments(repo, pr_number, new_comments)
    except urllib.error.HTTPError as e:
        if e.code == 403:
            print(
                "Cannot read PR comments (fork PR with read-only token). "
                "Skipping inline review comments.",
                file=sys.stderr,
            )
            return
        raise

    posted = 0
    failed = 0
    for comment in to_post:
        payload = {k: v for k, v in comment.items() if k != "fingerprint"}
        try:
            github_api("POST", f"/repos/{repo}/pulls/{pr_number}/comments", payload)
            posted += 1
        except urllib.error.HTTPError as e:
            if e.code == 403:
                print(
                    "Cannot post PR comments (fork PR with read-only token). "
                    "Skipping inline review comments.",
                    file=sys.stderr,
                )
                return
            if e.code in (401, 429):
                raise
            failed += 1

    kept = len(new_comments) - len(to_post)
    parts = [f"Posted {posted} new comment(s)", f"{kept} unchanged"]
    if failed:
        parts.append(f"{failed} failed")
    print(", ".join(parts) + ".")


if __name__ == "__main__":
    main()

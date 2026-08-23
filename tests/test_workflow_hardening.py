"""Regression guards for privileged workflow trust boundaries."""

import json
import os
from pathlib import Path
import subprocess

from ruamel.yaml import YAML

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _yaml(path: str):
    return YAML(typ="safe").load(_read(path))


def _isolated_git_env(**overrides: str) -> dict[str, str]:
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    env.update(overrides)
    return env


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        env=_isolated_git_env(),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_review_action_resolves_fork_pr_from_workflow_run_head_sha():
    action = _read("review/action.yml")
    parsed = _yaml("review/action.yml")

    assert "github.event.workflow_run.pull_requests[0]" not in action
    assert "github.event.workflow_run.head_sha" in action
    assert "commits/${EVENT_HEAD_SHA}/pulls" in action
    assert "Could not resolve a PR" in action
    assert "superseded PR" in action
    assert parsed["inputs"]["comment-author"]["default"] == "github-actions[bot]"


def test_issue_solver_uses_graphql_content_edit_history():
    workflow = _read(".github/workflows/skillsaw-issue-solver.yml")

    assert "userContentEdits(last:1)" in workflow
    assert "nodes{editedAt}" in workflow
    assert 'select(.event == "edited")' not in workflow


def test_claude_workflows_use_auto_permission_mode():
    invocations = []
    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        workflow = _yaml(str(path.relative_to(ROOT)))
        for job in workflow.get("jobs", {}).values():
            for step in job.get("steps", []):
                if str(step.get("uses", "")).startswith("anthropics/claude-code-action@"):
                    invocations.append((path, step))

    assert invocations
    for path, step in invocations:
        assert "--permission-mode auto" in step.get("with", {}).get("claude_args", ""), path


def test_pr_followup_restricts_bot_comments_and_broad_pr_commands():
    workflow = _read(".github/workflows/skillsaw-pr-followup.yml")
    parsed = _yaml(".github/workflows/skillsaw-pr-followup.yml")
    steps = parsed["jobs"]["follow-up"]["steps"]
    record_step = next(step for step in steps if step.get("id") == "before")
    verify_step = next(step for step in steps if step.get("name", "").startswith("Verify "))

    trusted_bots = workflow.split("TRUSTED_BOTS=", 1)[1].splitlines()[0].strip("'")
    assert set(json.loads(trusted_bots)) == {
        "coderabbitai[bot]",
        "codecov[bot]",
        "github-actions[bot]",
        "devin-ai-integration[bot]",
        "chatgpt-codex-connector[bot]",
    }
    assert "Bash(gh pr:*)" not in workflow
    assert "Bash(gh pr view:*)" in workflow
    assert "Bash(gh pr checks:*)" in workflow
    assert "Bash(gh api" not in workflow
    assert "gh auth setup-git" not in workflow
    assert "Agent left uncommitted changes" in workflow
    assert "Agent left local HEAD" in workflow
    assert "was not pushed to PR head" in workflow
    assert "Agent did not push a new PR head; nothing to verify" in workflow
    assert "No unprivileged Tests run started" in workflow
    assert parsed["permissions"]["actions"] == "read"
    assert record_step["name"] == "Record Git state before follow-up"
    assert verify_step["env"]["BEFORE_SHA"] == "${{ steps.before.outputs.head_sha }}"
    assert verify_step["env"]["CHECKOUT_SHA"] == "${{ steps.before.outputs.checkout_sha }}"


def test_pr_followup_skill_does_not_fetch_unfiltered_comments():
    skill = _read(".apm/skills/skillsaw-pr-followup/SKILL.md")

    assert "gh pr view <number> --comments" not in skill
    assert "Use only review comments supplied" in skill
    assert "PR metadata, not comments" in skill


def test_pr_followup_distinguishes_unpushed_commit_from_no_change(tmp_path, monkeypatch):
    steps = _yaml(".github/workflows/skillsaw-pr-followup.yml")["jobs"]["follow-up"]["steps"]
    verify_script = next(
        step["run"] for step in steps if step.get("name", "").startswith("Verify ")
    ).replace("${{ github.repository }}", "owner/repo")

    repo = tmp_path / "repo"
    repo.mkdir()
    hostile_config = tmp_path / "hostile.gitconfig"
    hostile_config.write_text("[commit]\n\tgpgsign = true\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(hostile_config))
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    tracked = repo / "tracked.txt"
    tracked.write_text("main\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-m", "main")
    checkout_sha = _git(repo, "rev-parse", "HEAD")

    _git(repo, "switch", "-c", "pr")
    tracked.write_text("pr\n", encoding="utf-8")
    _git(repo, "commit", "-am", "pr head")
    before_sha = _git(repo, "rev-parse", "HEAD")
    tracked.write_text("local only\n", encoding="utf-8")
    _git(repo, "commit", "-am", "unpushed agent commit")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$FAKE_HEAD_SHA\"\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    env = _isolated_git_env(
        BEFORE_SHA=before_sha,
        CHECKOUT_SHA=checkout_sha,
        FAKE_HEAD_SHA=before_sha,
        GH_TOKEN="test",
        PATH=f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        PR_NUMBER="1",
    )

    def run_verify():
        return subprocess.run(
            ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", verify_script],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )

    unpushed = run_verify()
    assert unpushed.returncode == 1
    assert "without pushing it to PR head" in unpushed.stderr

    _git(repo, "switch", "main")
    no_checkout = run_verify()
    assert no_checkout.returncode == 0
    assert "nothing to verify" in no_checkout.stdout

    _git(repo, "switch", "--detach", before_sha)
    unchanged_pr = run_verify()
    assert unchanged_pr.returncode == 0
    assert "nothing to verify" in unchanged_pr.stdout


def test_codecov_uses_oidc_without_a_repository_secret():
    workflow = _read(".github/workflows/test.yml")
    parsed = _yaml(".github/workflows/test.yml")

    assert "use_oidc: true" in workflow
    assert "CODECOV_TOKEN" not in workflow
    assert parsed["jobs"]["test"]["permissions"] == {
        "contents": "read",
        "id-token": "write",
    }


def test_dependabot_tracks_the_digest_pinned_docker_base():
    config = _yaml(".github/dependabot.yml")
    ecosystems = {update["package-ecosystem"] for update in config["updates"]}
    assert "docker" in ecosystems

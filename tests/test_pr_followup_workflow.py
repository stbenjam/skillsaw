"""Executable regression guard for the privileged PR-followup workflow."""

import os
from pathlib import Path
import subprocess

from ruamel.yaml import YAML

ROOT = Path(__file__).resolve().parents[1]


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
        timeout=10,
    )
    return result.stdout.strip()


def test_verify_step_rejects_unpushed_commit_but_allows_noop(tmp_path, monkeypatch):
    workflow_path = ROOT / ".github/workflows/skillsaw-pr-followup.yml"
    workflow = YAML(typ="safe").load(workflow_path.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["follow-up"]["steps"]
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
    fake_gh.write_text("#!/bin/sh\nprintf '%s\\n' \"$FAKE_HEAD_SHA\"\n", encoding="utf-8")
    fake_gh.chmod(0o755)
    env = _isolated_git_env(
        BEFORE_SHA=before_sha,
        CHECKOUT_SHA=checkout_sha,
        FAKE_HEAD_SHA=before_sha,
        GH_TOKEN="test",
        PATH=f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        PR_NUMBER="1",
    )

    def run_verify() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", verify_script],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
            timeout=5,
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

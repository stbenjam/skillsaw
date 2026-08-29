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
    assert '--argjson pr "$PR_NUMBER"' in action
    assert ".head.sha == $sha and .number == $pr" in action
    assert "Could not resolve a PR" in action
    assert "superseded PR" in action
    assert parsed["inputs"]["comment-author"]["default"] == "github-actions[bot]"


def test_issue_solver_uses_graphql_content_edit_history():
    workflow = _read(".github/workflows/skillsaw-issue-solver.yml")

    assert "--paginate --slurp" in workflow
    assert "[.[][] | select" in workflow
    assert "current agent label has no resolvable label event" in workflow
    assert "userContentEdits(last:1)" in workflow
    assert "nodes{editedAt}" in workflow
    assert 'select(.event == "edited")' not in workflow
    assert "AUTH_COUNT" not in workflow
    assert "reapply the label to approve it" in workflow


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
        claude_args = step.get("with", {}).get("claude_args", "")
        assert "--permission-mode auto" in claude_args, path
        assert "--allowedTools" not in claude_args, path


def test_pr_followup_restricts_bot_comments_and_validates_agent_results():
    workflow = _read(".github/workflows/skillsaw-pr-followup.yml")
    parsed = _yaml(".github/workflows/skillsaw-pr-followup.yml")
    steps = parsed["jobs"]["follow-up"]["steps"]
    discover_permissions = parsed["jobs"]["discover"]["permissions"]
    follow_up_permissions = parsed["jobs"]["follow-up"]["permissions"]
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
    assert "gh auth setup-git" not in workflow
    assert "Agent left uncommitted changes" in workflow
    assert "Agent left local HEAD" in workflow
    assert "was not pushed to PR head" in workflow
    assert "Agent did not push a new PR head; nothing to verify" in workflow
    assert "No unprivileged Tests run started" in workflow
    assert '--argjson pr "$PR_NUMBER"' in verify_step["run"]
    assert ".pull_requests | any(.number == $pr)" in verify_step["run"]
    assert "permissions" not in parsed
    assert discover_permissions == {
        "contents": "read",
        "pull-requests": "read",
        "issues": "read",
    }
    assert follow_up_permissions == {
        "actions": "read",
        "contents": "write",
        "pull-requests": "write",
        "issues": "write",
        "id-token": "write",
    }
    assert record_step["name"] == "Record Git state before follow-up"
    assert verify_step["env"]["BEFORE_SHA"] == "${{ steps.before.outputs.head_sha }}"
    assert verify_step["env"]["CHECKOUT_SHA"] == "${{ steps.before.outputs.checkout_sha }}"


def test_pr_followup_skill_does_not_fetch_unfiltered_comments():
    skill = _read(".apm/skills/skillsaw-pr-followup/SKILL.md")
    workflow = _read(".github/workflows/skillsaw-pr-followup.yml")
    trusted_bots = json.loads(workflow.split("TRUSTED_BOTS=", 1)[1].splitlines()[0].strip("'"))

    assert "gh pr view <number> --comments" not in skill
    assert "Use only review comments supplied" in skill
    assert "PR metadata, not comments" in skill
    for trusted_bot in trusted_bots:
        assert trusted_bot in skill


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
    test_job = parsed["jobs"]["test"]
    coverage_job = parsed["jobs"]["coverage"]

    assert "use_oidc: true" in workflow
    assert "CODECOV_TOKEN" not in workflow
    assert test_job["permissions"] == {"contents": "read"}
    assert "3.14" not in test_job["strategy"]["matrix"]["python-version"]
    matrix_test_step = next(
        step for step in test_job["steps"] if step.get("name", "").startswith("Run ")
    )
    assert matrix_test_step["run"] == ".venv/bin/pytest tests/ -v -n auto"
    assert "--cov" not in matrix_test_step["run"]
    assert coverage_job["name"] == "test (3.14)"
    assert coverage_job["permissions"] == {
        "contents": "read",
        "id-token": "write",
    }
    assert not any(
        "codecov/codecov-action@" in str(step.get("uses", "")) for step in test_job["steps"]
    )
    assert any(
        "codecov/codecov-action@" in str(step.get("uses", "")) for step in coverage_job["steps"]
    )


def test_dependabot_tracks_the_digest_pinned_docker_base():
    config = _yaml(".github/dependabot.yml")
    ecosystems = {update["package-ecosystem"] for update in config["updates"]}
    assert "docker" in ecosystems


def test_zizmor_workflow_is_pinned_blocking_and_unprivileged():
    workflow = _yaml(".github/workflows/zizmor.yml")
    steps = workflow["jobs"]["zizmor"]["steps"]
    checkout = next(step for step in steps if step["name"] == "Checkout repository")
    policy_checkout = next(
        step for step in steps if step["name"] == "Checkout immutable zizmor policy"
    )
    scan = next(step for step in steps if step["name"] == "Run zizmor")

    assert workflow["permissions"] == {}
    assert "permissions" not in workflow["jobs"]["zizmor"]
    assert checkout["uses"] == ("actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1")
    assert checkout["with"]["persist-credentials"] is False
    assert policy_checkout["uses"] == checkout["uses"]
    assert policy_checkout["with"] == {
        "ref": "eecf9836c88b3c73103e94c6b0a8e935508af689",
        "path": ".trusted-zizmor",
        "sparse-checkout": "zizmor.yml",
        "sparse-checkout-cone-mode": False,
        "persist-credentials": False,
    }
    assert scan["uses"] == ("zizmorcore/zizmor-action@3dc1ecc9bcb9e94e9b2c709687979e1298497054")
    assert scan["with"] == {
        "version": "v1.29.0",
        "config": ".trusted-zizmor/zizmor.yml",
        "advanced-security": False,
        "annotations": True,
    }


def _lint_step_args_script() -> str:
    """The ARGS-building prefix of the shared Action runner, made runnable.

    Cut at REPORT_FILE= so the input handling can be exercised without GNU
    mktemp, an installed skillsaw, or a $GITHUB_OUTPUT to append to.
    """
    script = _read("scripts/run-action-lint.sh")
    prefix, marker, _rest = script.partition("REPORT_FILE=")
    assert marker, "shared Action runner no longer builds REPORT_FILE"
    return prefix + 'echo "ARGS=${ARGS[*]}"\n'


def _run_lint_args(**overrides: str) -> subprocess.CompletedProcess:
    env = {
        "PATH": os.environ["PATH"],
        "SKILLSAW_STRICT": "false",
        "SKILLSAW_FAIL_ON": "",
        "SKILLSAW_RULE": "",
        "SKILLSAW_VERBOSE": "false",
        "SKILLSAW_NO_CUSTOM_RULES": "true",
        "SKILLSAW_NO_NETWORK_INPUT": "true",
    }
    env.update(overrides)
    return subprocess.run(
        ["bash", "--noprofile", "--norc", "-c", _lint_step_args_script()],
        env=env,
        capture_output=True,
        text=True,
    )


def test_action_rule_input_splits_on_lines_and_commas():
    newlines = _run_lint_args(SKILLSAW_RULE="content-weak-language\ncontent-tautological\n")
    commas = _run_lint_args(SKILLSAW_RULE="content-weak-language, content-tautological")

    for result in (newlines, commas):
        assert result.returncode == 0, result.stderr
        assert "--rule content-weak-language --rule content-tautological" in result.stdout


def test_action_rule_input_admits_only_kebab_case_ids():
    # Reject anything outside the rule-id grammar before it reaches the CLI.
    # Uppercase is rejected too: the guard runs under LC_ALL=C because [a-z]
    # collates case-insensitively in most other locales.
    for hostile in (
        "content-weak-language --allow-private-hosts",
        "*",
        "../../etc/passwd",
        "Content-Weak-Language",
        "content_weak_language",
        "content-weak-language;id",
    ):
        for locale in ("C", "en_US.UTF-8"):
            result = _run_lint_args(SKILLSAW_RULE=hostile, LC_ALL=locale)
            assert result.returncode == 1, (hostile, locale, result.stdout)
            assert "Invalid rule id" in result.stderr, (hostile, locale)
            assert "--rule" not in result.stdout, (hostile, locale)


def test_action_rule_input_does_not_itself_grant_network_access():
    # Selecting a rule is not permission to run it: the network gate is a
    # separate input, so naming a network rule leaves --no-network in place
    # and the CLI refuses the combination rather than reporting no dead links.
    selected = _run_lint_args(SKILLSAW_RULE="content-broken-external-reference")
    assert "--rule content-broken-external-reference" in selected.stdout
    assert "--no-network" in selected.stdout

    granted = _run_lint_args(
        SKILLSAW_RULE="content-broken-external-reference",
        SKILLSAW_NO_NETWORK_INPUT="false",
    )
    assert "--rule content-broken-external-reference" in granted.stdout
    assert "--no-network" not in granted.stdout


def test_shared_action_runner_installs_lints_and_publishes_outputs(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    action_root = tmp_path / "action source"
    action_root.mkdir()
    (action_root / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    captured_args = tmp_path / "skillsaw-args"
    output_file = tmp_path / "github-output"

    fake_pip = fake_bin / "pip"
    fake_pip.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_pip.chmod(0o755)
    fake_skillsaw = fake_bin / "skillsaw"
    fake_skillsaw.write_text(
        """#!/usr/bin/env bash
printf '%s\\n' "$@" > "$CAPTURED_ARGS"
while [[ $# -gt 0 ]]; do
  if [[ "$1" == "--output" ]]; then
    report="${2#json:}"
    printf '%s\\n' '{"summary":{"errors":2,"warnings":3}}' > "$report"
    break
  fi
  shift
done
exit 1
""",
        encoding="utf-8",
    )
    fake_skillsaw.chmod(0o755)

    env = {
        **os.environ,
        "CAPTURED_ARGS": str(captured_args),
        "GITHUB_OUTPUT": str(output_file),
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "SKILLSAW_ACTION_ROOT": str(action_root),
        "SKILLSAW_NO_CUSTOM_RULES": "true",
        "SKILLSAW_NO_NETWORK_INPUT": "false",
        "SKILLSAW_PATH": "context path",
        "SKILLSAW_REPORT_DIRECTORY": str(tmp_path),
        "SKILLSAW_RULE": "content-weak-language,content-tautological",
        "SKILLSAW_STRICT": "true",
        "SKILLSAW_VERBOSE": "true",
    }
    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "run-action-lint.sh")],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    arguments = captured_args.read_text(encoding="utf-8").splitlines()
    assert arguments[:9] == [
        "lint",
        "--strict",
        "--rule",
        "content-weak-language",
        "--rule",
        "content-tautological",
        "-v",
        "--no-custom-rules",
        "--format",
    ]
    assert "--no-network" not in arguments
    assert arguments[-1] == "context path"
    outputs = output_file.read_text(encoding="utf-8")
    assert "exit-code=1" in outputs
    assert "errors=2" in outputs
    assert "warnings=3" in outputs


def test_dedicated_link_check_action_owns_safe_configuration_and_issue_reporting():
    action_text = _read("link-check/action.yml")
    action = _yaml("link-check/action.yml")
    inputs = action["inputs"]
    steps = action["runs"]["steps"]
    lint_index = next(index for index, step in enumerate(steps) if step.get("id") == "lint")
    issue_index = next(
        index for index, step in enumerate(steps) if step.get("name", "").startswith("Create or")
    )
    exit_index = next(
        index for index, step in enumerate(steps) if step.get("name", "").startswith("Exit with")
    )
    lint = steps[lint_index]
    issue = steps[issue_index]

    assert inputs["create-issue"]["default"] == "true"
    assert inputs["token"]["default"] == "${{ github.token }}"
    assert inputs["issue-author"]["default"] == "github-actions[bot]"
    root_lint = next(
        step for step in _yaml("action.yml")["runs"]["steps"] if step.get("id") == "lint"
    )
    assert root_lint["run"].endswith('/scripts/run-action-lint.sh"')
    assert lint["run"].endswith('/../scripts/run-action-lint.sh"')
    assert lint["env"]["SKILLSAW_RULE"] == "content-broken-external-reference"
    assert lint["env"]["SKILLSAW_NO_CUSTOM_RULES"] == "true"
    assert lint["env"]["SKILLSAW_STRICT"] == "true"
    assert lint["env"]["SKILLSAW_VERBOSE"] == "true"
    assert lint["env"]["SKILLSAW_NO_NETWORK_INPUT"] == "false"
    assert "uses: stbenjam/skillsaw@" not in action_text
    assert "--allow-private-hosts" not in action_text
    assert issue["env"]["GITHUB_TOKEN"] == "${{ inputs.token }}"
    assert "report_issue.py" in issue["run"]
    # Lint records its exit status, reporting still runs, then the Action turns
    # the confirmed warning into a failed scheduled job.
    assert lint_index < issue_index < exit_index


def test_scheduled_link_check_recipe_matches_the_onboard_skill():
    # The docs recipe and the workflow the onboard skill offers must both use
    # the packaged Action rather than reimplementing its security-sensitive
    # network and issue-reporting configuration in every consumer repository.
    recipe = _read("docs/ci.md").split("## Scheduled external link checking", 1)[1]
    recipe = recipe.split("### Refusing network access", 1)[0]
    skill = _read("skills/skillsaw-onboard/references/07-ci.md")
    skill = skill.split("Offer the dedicated weekly dead-link check", 1)[1]
    skill = skill.split("## GitLab CI", 1)[0]

    for source in (recipe, skill):
        assert "stbenjam/skillsaw/link-check@" in source
        assert "issues: write" in source
        assert "skillsaw-link-check" in source
        assert "name: link-check" in source
        assert "rule: content-broken-external-reference" not in source
        assert "no-network: false" not in source
        assert "strict: true" not in source
    assert "create-issue: false" in recipe


def test_onboard_skill_discloses_exactly_one_reference_per_step():
    relative_references = [
        "01-install.md",
        "02-initial-scan.md",
        "03-autofix.md",
        "04-manual-fixes.md",
        "05-baseline.md",
        "06-configuration.md",
        "07-ci.md",
        "08-makefile.md",
        "09-badge.md",
        "10-verify.md",
    ]
    for root in ("skills", ".agents/skills", ".claude/skills"):
        skill_root = ROOT / root / "skillsaw-onboard"
        router = (skill_root / "SKILL.md").read_text(encoding="utf-8")
        assert "Read only the\ncurrent step's reference; do not preload later references" in router
        assert len(router.splitlines()) < 40
        for reference in relative_references:
            assert f"references/{reference}" in router
            assert (skill_root / "references" / reference).is_file()

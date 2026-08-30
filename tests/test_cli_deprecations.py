"""CLI deprecation notices for features leaving after 0.20.0."""

from tests.cli_runner import run_cli


def _warning(command: str) -> str:
    return (
        f"Warning: 'skillsaw {command}' is deprecated and will be removed "
        "in an upcoming release."
    )


def _assert_one_stderr_warning(result, command: str) -> None:
    warning = _warning(command)
    assert result.stderr.count(warning) == 1
    assert warning not in result.stdout


def test_deprecated_command_help_warns_once_per_invocation() -> None:
    for command in ("add", "docs"):
        for _ in range(2):
            result = run_cli([command, "--help"])
            assert result.returncode == 0
            assert "Deprecated:" in result.stdout
            _assert_one_stderr_warning(result, command)


def test_add_still_scaffolds_with_one_deprecation_warning(tmp_path) -> None:
    result = run_cli(["add", "skill", "release-helper", "--path", tmp_path])

    assert result.returncode == 0
    assert (tmp_path / "release-helper" / "SKILL.md").is_file()
    _assert_one_stderr_warning(result, "add")


def test_docs_still_generates_with_one_deprecation_warning(tmp_path) -> None:
    skill_dir = tmp_path / "release-helper"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: release-helper\n"
        "description: Prepare and verify a project release\n"
        "---\n\n"
        "# Release Helper\n\n"
        "Review the release checklist and report any blockers.\n",
        encoding="utf-8",
    )
    output = tmp_path / "release-helper.md"

    result = run_cli(["docs", skill_dir, "--format", "markdown", "--output", output])

    assert result.returncode == 0
    assert output.is_file()
    _assert_one_stderr_warning(result, "docs")


def test_deprecated_command_parse_errors_still_warn_once() -> None:
    for command, args in (
        ("add", ["add", "unknown-component"]),
        ("docs", ["docs", "--format", "unknown-format"]),
    ):
        result = run_cli(args)

        assert result.returncode == 2
        assert result.stdout == ""
        _assert_one_stderr_warning(result, command)


def test_unrelated_command_has_no_feature_deprecation_warning() -> None:
    result = run_cli(["list-rules"])

    assert result.returncode == 0
    assert "is deprecated and will be removed in an upcoming release" not in result.stderr
    assert "is deprecated and will be removed in an upcoming release" not in result.stdout

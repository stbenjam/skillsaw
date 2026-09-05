"""Incomplete directory traversal must remain visible beside readable content."""

import errno
import json
import os
from pathlib import Path
import shutil

import pytest

from skillsaw.blocks import CursorRuleBlock
from skillsaw.context import RepositoryContext
from tests.cli_runner import run_cli
from tests.test_integration import copy_fixture


def _repo(tmp_path, nested=False):
    repo = copy_fixture("cursor-rules/clean", tmp_path)
    (repo / ".skillsaw.yaml").write_text(json.dumps({"plugins": False}))
    if nested:
        denied = repo / "packages/service"
        shutil.copytree(repo / ".cursor", denied / ".cursor")
        target = denied / ".cursor/rules/backend/api.mdc"
    else:
        denied = repo / ".cursor/rules/backend"
        target = denied / "api.mdc"
    target.write_text(target.read_text().replace("alwaysApply: false", 'alwaysApply: "invalid"'))
    return repo, denied, target


def _deny_scandir(monkeypatch, denied):
    scandir = os.scandir
    attempts = []

    def denied_scan(path):
        if isinstance(path, (str, Path)) and Path(path) == denied:
            attempts.append(path)
            raise PermissionError(errno.EACCES, "Permission denied", str(denied))
        return scandir(path)

    monkeypatch.setattr(os, "scandir", denied_scan)
    return attempts


def _lint(repo):
    result = run_cli(
        [
            "lint",
            repo,
            "--rule",
            "cursor-rules-valid",
            "--format",
            "json",
            "--verbose",
            "--no-custom-rules",
            "--no-plugins",
            "--no-baseline",
        ]
    )
    return result.returncode, json.loads(result.stdout)


@pytest.mark.parametrize("nested", [False, True])
def test_denied_walk_is_reported_and_readable_targets_survive(tmp_path, monkeypatch, nested):
    repo, denied, target = _repo(tmp_path, nested)
    with monkeypatch.context() as patch:
        attempts = _deny_scandir(patch, denied)
        context = RepositoryContext(repo)
        paths = {node.path for node in context.lint_tree.find(CursorRuleBlock)}
        assert repo / ".cursor/rules/conventions.mdc" in paths
        assert target not in paths
        assert len(context.lint_tree_errors) == 1
        assert str(denied) in context.lint_tree_errors[0]
        assert attempts

        code, report = _lint(repo)
        assert code == 1
        assert [v["rule_id"] for v in report["violations"]] == ["repository-path-error"]
        assert report["violations"][0]["severity"] == "error"
        assert str(denied) in report["violations"][0]["message"]
        assert report["summary"]["grade"]["letter"] != "A+"

        tree = run_cli(["tree", repo])
        assert tree.returncode == 1
        assert str(denied) in tree.stderr
        assert "Permission denied" in tree.stderr

    # The same bytes, once readable, reach the owning rule with no traversal error.
    code, report = _lint(repo)
    assert code == 1
    assert [(v["rule_id"], v["file_path"]) for v in report["violations"]] == [
        ("cursor-rules-valid", target.relative_to(repo).as_posix())
    ]
    assert "alwaysApply" in report["violations"][0]["message"]


def test_attachment_failure_after_the_shared_scan_is_reported(tmp_path, monkeypatch):
    repo, denied, target = _repo(tmp_path)
    context = RepositoryContext(repo)
    assert context._repository_scan().tool_dirs[".cursor"] == (repo / ".cursor",)
    attempts = _deny_scandir(monkeypatch, denied)

    paths = {node.path for node in context.lint_tree.find(CursorRuleBlock)}

    assert attempts
    assert target not in paths
    assert repo / ".cursor/rules/conventions.mdc" in paths
    assert len(context.lint_tree_errors) == 1
    assert str(denied) in context.lint_tree_errors[0]


@pytest.mark.parametrize("excluded", [".cursor/rules/backend", ".cursor/rules"])
def test_excluded_unreadable_directory_does_not_report_an_error(tmp_path, monkeypatch, excluded):
    repo, denied, _ = _repo(tmp_path)
    (repo / ".skillsaw.yaml").write_text(json.dumps({"exclude": [excluded], "plugins": False}))
    _deny_scandir(monkeypatch, denied)

    code, report = _lint(repo)

    assert code == 0
    assert report["violations"] == []
    tree = run_cli(["tree", repo])
    assert tree.returncode == 0, tree.stderr


def test_skipped_dependency_directory_is_not_an_unreadable_error(tmp_path, monkeypatch):
    repo = copy_fixture("cursor-rules/clean", tmp_path)
    denied = repo / "node_modules"
    denied.mkdir()
    attempts = _deny_scandir(monkeypatch, denied)

    code, report = _lint(repo)

    assert code == 0
    assert report["violations"] == []
    assert attempts == []


def test_readable_sibling_findings_survive_a_traversal_failure(tmp_path, monkeypatch):
    repo, denied, _ = _repo(tmp_path, nested=True)
    readable = repo / ".cursor/rules/backend/api.mdc"
    readable.write_text(
        readable.read_text().replace("alwaysApply: false", 'alwaysApply: "invalid"')
    )
    _deny_scandir(monkeypatch, denied)

    code, report = _lint(repo)

    assert code == 1
    assert sorted(v["rule_id"] for v in report["violations"]) == [
        "cursor-rules-valid",
        "repository-path-error",
    ]
    finding = next(v for v in report["violations"] if v["rule_id"] == "cursor-rules-valid")
    assert finding["file_path"] == ".cursor/rules/backend/api.mdc"
    assert "alwaysApply" in finding["message"]

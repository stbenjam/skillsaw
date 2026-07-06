"""Tests for the context-window budget report (skillsaw budget)."""

import json
import os
import subprocess
import sys

import pytest

from skillsaw.budget import BudgetItem, compute_budget
from skillsaw.context import RepositoryContext

from .test_integration import copy_fixture


def run_budget(path, *extra_args):
    return subprocess.run(
        [sys.executable, "-m", "skillsaw", "budget", str(path), *extra_args],
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "NO_COLOR": "1"},
    )


class TestComputeBudget:
    def test_session_and_on_demand_split(self, tmp_path):
        repo = copy_fixture("budget/mixed", tmp_path)
        report = compute_budget(RepositoryContext(repo))

        session_paths = {i.path for i in report.session_files}
        assert "CLAUDE.md" in session_paths
        assert ".claude/rules/style.md" in session_paths

        on_demand_paths = {i.path for i in report.on_demand}
        assert ".claude/skills/deploy-helper/SKILL.md" in on_demand_paths
        assert ".claude/skills/deploy-helper/references/checklist.md" in on_demand_paths
        assert ".claude/commands/ship.md" in on_demand_paths
        assert ".claude/agents/reviewer.md" in on_demand_paths

        # Session files never leak into on-demand and vice versa.
        assert not session_paths & on_demand_paths

    def test_metadata_groups(self, tmp_path):
        repo = copy_fixture("budget/mixed", tmp_path)
        report = compute_budget(RepositoryContext(repo))

        groups = {g.kind: g for g in report.metadata}
        assert set(groups) == {"skill", "command", "agent"}
        assert [i.label for i in groups["skill"].items] == ["deploy-helper"]
        assert groups["skill"].items[0].tokens > 0
        # Commands without a frontmatter name fall back to the file stem.
        assert [i.label for i in groups["command"].items] == ["ship"]
        assert [i.label for i in groups["agent"].items] == ["reviewer"]
        # No limit category exists for agent descriptions.
        assert groups["agent"].items[0].status is None
        assert groups["skill"].items[0].status == "ok"

    def test_totals_and_window_percent(self, tmp_path):
        repo = copy_fixture("budget/mixed", tmp_path)
        report = compute_budget(RepositoryContext(repo), window=1000)

        file_total = sum(i.tokens for i in report.session_files)
        meta_total = sum(g.total for g in report.metadata)
        assert report.session_total == file_total + meta_total
        assert report.window_percent == pytest.approx(report.session_total / 1000 * 100)
        assert report.on_demand_total == sum(i.tokens for i in report.on_demand)

    def test_custom_limits_set_status(self, tmp_path):
        repo = copy_fixture("budget/mixed", tmp_path)
        report = compute_budget(
            RepositoryContext(repo),
            user_limits={
                "claude-md": {"warn": 10, "error": 100},
                "skill": 10,  # int form: warn-only
                "skill-description": {"warn": 1, "error": 5},
            },
        )

        claude = next(i for i in report.session_files if i.path == "CLAUDE.md")
        assert claude.status == "error"
        skill = next(i for i in report.on_demand if i.category == "skill")
        assert skill.status == "warn"
        skill_desc = next(g for g in report.metadata if g.kind == "skill").items[0]
        assert skill_desc.status == "error"

        over = report.over_limit()
        assert claude in over and skill in over and skill_desc in over

    def test_no_duplicate_paths(self, tmp_path):
        repo = copy_fixture("budget/mixed", tmp_path)
        report = compute_budget(RepositoryContext(repo))

        paths = [i.path for i in report.session_files + report.on_demand]
        assert len(paths) == len(set(paths))

    def test_to_dict_shape(self, tmp_path):
        repo = copy_fixture("budget/mixed", tmp_path)
        payload = compute_budget(RepositoryContext(repo)).to_dict()

        assert payload["window"] == 200_000
        session = payload["session_start"]
        assert session["total_tokens"] > 0
        assert isinstance(session["window_percent"], float)
        assert {f["path"] for f in session["files"]} >= {"CLAUDE.md"}
        assert session["metadata"]["skills"]["count"] == 1
        assert payload["on_demand"]["total_tokens"] > 0
        assert payload["limits"]["claude-md"] == {"warn": 6000, "error": 12000}

    def test_items_sorted_by_tokens_descending(self, tmp_path):
        repo = copy_fixture("budget/mixed", tmp_path)
        report = compute_budget(RepositoryContext(repo))

        for items in (report.session_files, report.on_demand):
            tokens = [i.tokens for i in items]
            assert tokens == sorted(tokens, reverse=True)


class TestBudgetCli:
    @pytest.mark.integration
    def test_text_output(self, tmp_path):
        repo = copy_fixture("budget/mixed", tmp_path)
        result = run_budget(repo)
        assert result.returncode == 0, result.stderr
        assert "SESSION START" in result.stdout
        assert "ON DEMAND" in result.stdout
        assert "CLAUDE.md" in result.stdout
        assert "skill descriptions (1)" in result.stdout

    @pytest.mark.integration
    def test_json_output(self, tmp_path):
        repo = copy_fixture("budget/mixed", tmp_path)
        result = run_budget(repo, "--format", "json")
        assert result.returncode == 0, result.stderr

        payload = json.loads(result.stdout)
        assert payload["session_start"]["total_tokens"] > 0
        files = {f["path"] for f in payload["session_start"]["files"]}
        assert "CLAUDE.md" in files

    @pytest.mark.integration
    def test_top_truncates_text_output(self, tmp_path):
        repo = copy_fixture("budget/mixed", tmp_path)
        result = run_budget(repo, "--top", "1")
        assert result.returncode == 0, result.stderr
        assert "top 1 of 4" in result.stdout
        assert "--top 0 for all" in result.stdout

    @pytest.mark.integration
    def test_window_changes_percentage(self, tmp_path):
        repo = copy_fixture("budget/mixed", tmp_path)
        result = run_budget(repo, "--format", "json", "--window", "1000")
        payload = json.loads(result.stdout)
        assert payload["window"] == 1000
        assert payload["session_start"]["window_percent"] > 10

    @pytest.mark.integration
    def test_limits_from_config_file(self, tmp_path):
        repo = copy_fixture("budget/mixed", tmp_path)
        (repo / ".skillsaw.yaml").write_text(
            "rules:\n"
            "  context-budget:\n"
            "    limits:\n"
            "      claude-md:\n"
            "        warn: 10\n"
            "        error: 50\n"
        )
        result = run_budget(repo, "--format", "json")
        payload = json.loads(result.stdout)
        claude = next(f for f in payload["session_start"]["files"] if f["path"] == "CLAUDE.md")
        assert claude["status"] == "error"
        assert payload["limits"]["claude-md"] == {"warn": 10, "error": 50}

    @pytest.mark.integration
    def test_over_limit_summary_in_text(self, tmp_path):
        repo = copy_fixture("budget/mixed", tmp_path)
        (repo / ".skillsaw.yaml").write_text(
            "rules:\n"
            "  context-budget:\n"
            "    limits:\n"
            "      claude-md:\n"
            "        warn: 10\n"
        )
        result = run_budget(repo)
        assert "over warn limit" in result.stdout
        assert "context-budget rule" in result.stdout

    @pytest.mark.integration
    def test_missing_path_exits_nonzero(self, tmp_path):
        result = run_budget(tmp_path / "does-not-exist")
        assert result.returncode == 1
        assert "Path not found" in result.stderr


class TestBudgetItem:
    def test_to_dict_omits_empty_fields(self):
        item = BudgetItem(label="x", category="skill", tokens=5)
        assert item.to_dict() == {"label": "x", "category": "skill", "tokens": 5}

        full = BudgetItem(label="x", category="skill", tokens=5, path="a/b", status="ok")
        assert full.to_dict()["path"] == "a/b"
        assert full.to_dict()["status"] == "ok"

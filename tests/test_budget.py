"""Tests for the context-window budget report (skillsaw context)."""

import json
import os
import subprocess
import sys

import pytest

from skillsaw.budget import (
    EXCLUDED_CATEGORIES,
    ON_DEMAND_CATEGORIES,
    SESSION_CATEGORIES,
    BudgetItem,
    compute_budget,
)
from skillsaw.context import RepositoryContext

from .test_integration import copy_fixture


def run_context(path, *extra_args):
    return subprocess.run(
        [sys.executable, "-m", "skillsaw", "context", str(path), *extra_args],
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
        assert "AGENTS.md" in session_paths
        assert "GEMINI.md" in session_paths
        assert ".github/copilot-instructions.md" in session_paths
        assert ".claude/rules/style.md" in session_paths

        on_demand_paths = {i.path for i in report.on_demand}
        assert ".claude/skills/deploy-helper/SKILL.md" in on_demand_paths
        assert ".claude/skills/deploy-helper/references/checklist.md" in on_demand_paths
        assert ".claude/commands/ship.md" in on_demand_paths
        assert ".claude/agents/reviewer.md" in on_demand_paths

        # Session files never leak into on-demand and vice versa. The only
        # legitimate cross-bucket paths are dual-role items: a file whose
        # body is on-demand but whose description/import is session cost.
        dual_role = {
            i.path
            for i in report.session_files
            if i.category in ("import", "cursor-rule-description")
        }
        assert not (session_paths & on_demand_paths) - dual_role

    def test_conditional_session_content_is_on_demand(self, tmp_path):
        """paths:-scoped rules, applyTo-scoped instruction files, and
        non-alwaysApply cursor rules are loaded when their paths match,
        not at session start."""
        repo = copy_fixture("budget/mixed", tmp_path)
        report = compute_budget(RepositoryContext(repo))

        session_paths = {i.path for i in report.session_files}
        on_demand_paths = {i.path for i in report.on_demand}
        assert ".cursor/rules/core-style.mdc" in session_paths  # alwaysApply: true
        assert ".cursor/rules/api-conventions.mdc" in on_demand_paths
        assert ".claude/rules/frontend.md" in on_demand_paths  # paths: scoped
        # applyTo: "**" applies everywhere -> session; narrower glob -> on demand
        assert ".github/instructions/general.instructions.md" in session_paths
        assert ".github/instructions/frontend.instructions.md" in on_demand_paths

    def test_imports_resolved_into_session(self, tmp_path):
        repo = copy_fixture("budget/mixed", tmp_path)
        report = compute_budget(RepositoryContext(repo))

        imported = next(i for i in report.session_files if i.path == "docs/architecture.md")
        assert imported.category == "import"
        assert imported.via == "CLAUDE.md"
        assert imported.tokens > 0
        # No limit category exists for imports; the context-budget rule
        # never sees them, so budget must not flag them.
        assert imported.status is None
        # Billed to the importing harness's session.
        assert "claude" in imported.harnesses

    def test_import_cycles_and_depth_are_bounded(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("# Guide\n\n@a.md\n\nGeneral notes here.\n")
        (tmp_path / "a.md").write_text("# A\n\n@b.md\n")
        (tmp_path / "b.md").write_text("# B\n\n@a.md\n\n@c.md\n")
        (tmp_path / "c.md").write_text("# C\n\n@d.md\n")
        (tmp_path / "d.md").write_text("# D\n\n@e.md\n")
        (tmp_path / "e.md").write_text("# E — beyond the four-hop limit\n")

        report = compute_budget(RepositoryContext(tmp_path))
        session_paths = [i.path for i in report.session_files]
        # Cycle a<->b counted once each; d is hop 4 (last allowed), e is hop 5.
        assert session_paths.count("a.md") == 1
        assert session_paths.count("b.md") == 1
        assert "d.md" in session_paths
        assert "e.md" not in session_paths

    def test_import_home_and_escaping_paths_skipped(self, tmp_path):
        outside = tmp_path / "outside.md"
        outside.write_text("# Outside the repo\n")
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "CLAUDE.md").write_text(
            "# Guide\n\n@~/private/notes.md\n\n@../outside.md\n\n@missing.md\n"
        )
        report = compute_budget(RepositoryContext(repo))
        assert [i.path for i in report.session_files] == ["CLAUDE.md"]

    def test_midline_and_list_item_imports_billed(self, tmp_path):
        # The canonical example from the Claude Code memory docs: imports
        # work anywhere in the file, not only at line start.
        (tmp_path / "CLAUDE.md").write_text(
            "See @README.md for project overview.\n\n"
            "# Additional Instructions\n\n"
            "- git workflow @docs/git-instructions.md\n"
        )
        (tmp_path / "README.md").write_text("# Project\n\nA service that processes orders.\n")
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "git-instructions.md").write_text("# Git\n\nRebase before merging.\n")

        report = compute_budget(RepositoryContext(tmp_path))
        session_paths = {i.path for i in report.session_files}
        assert "README.md" in session_paths
        assert "docs/git-instructions.md" in session_paths

    def test_import_of_on_demand_file_billed_to_session(self, tmp_path):
        # An @-imported skill reference is loaded at session start for the
        # importer AND remains an on-demand asset: both roles are billed,
        # and its own transitive imports are still traversed.
        skill = tmp_path / ".claude" / "skills" / "deploy"
        (skill / "references").mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: deploy\ndescription: Deploy the service to production\n---\n\n"
            "# Deploy\n\nFollow [the runbook](references/runbook.md).\n"
        )
        (skill / "references" / "runbook.md").write_text(
            "# Runbook\n\nDrain traffic first.\n\n@../../../../docs/deep.md\n"
        )
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "deep.md").write_text("# Deep\n\nTransitively imported content.\n")
        (tmp_path / "CLAUDE.md").write_text(
            "# Guide\n\n@.claude/skills/deploy/references/runbook.md\n"
        )

        report = compute_budget(RepositoryContext(tmp_path))
        session = {(i.path, i.category) for i in report.session_files}
        assert (".claude/skills/deploy/references/runbook.md", "import") in session
        assert ("docs/deep.md", "import") in session
        # Still an on-demand asset too.
        assert ".claude/skills/deploy/references/runbook.md" in {i.path for i in report.on_demand}

    def test_symlinked_claude_agents_serve_both_harnesses(self, tmp_path):
        # The docs-recommended `ln -s AGENTS.md CLAUDE.md` layout: one file,
        # both harnesses — the dedupe must union, not drop, attribution.
        (tmp_path / "AGENTS.md").write_text(
            "# Guide\n\nRun make test before pushing. Keep handlers thin.\n"
        )
        os.symlink(tmp_path / "AGENTS.md", tmp_path / "CLAUDE.md")

        report = compute_budget(RepositoryContext(tmp_path))
        assert len(report.session_files) == 1
        item = report.session_files[0]
        assert "claude" in item.harnesses
        assert "default" in item.harnesses
        assert report.by_harness["claude"] == item.tokens

    def test_transitive_import_harness_union_propagates(self, tmp_path):
        # Two roots share an import chain; the second root's attribution
        # must reach transitive imports, not just the first hop.
        (tmp_path / "CLAUDE.md").write_text("# C\n\n@a.md\n")
        (tmp_path / "GEMINI.md").write_text("# G\n\n@a.md\n")
        (tmp_path / "a.md").write_text("# A\n\n@b.md\n")
        (tmp_path / "b.md").write_text("# B\n\nShared leaf content for both harnesses.\n")

        report = compute_budget(RepositoryContext(tmp_path))
        b = next(i for i in report.session_files if i.path == "b.md")
        assert {"claude", "gemini"} <= set(b.harnesses)

    def test_gemini_reads_agents_md_only_without_gemini_md(self, tmp_path):
        (tmp_path / "AGENTS.md").write_text("# Guide\n\nGeneric agent instructions here.\n")
        report = compute_budget(RepositoryContext(tmp_path))
        agents = next(i for i in report.session_files if i.path == "AGENTS.md")
        assert "gemini" in agents.harnesses  # no GEMINI.md -> AGENTS.md serves gemini

    def test_claude_local_and_dot_claude_memory_billed(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("# Guide\n\nProject instructions.\n")
        (tmp_path / "CLAUDE.local.md").write_text("# Local\n\nMy machine-specific notes.\n")
        dot = tmp_path / ".claude"
        dot.mkdir()
        (dot / "CLAUDE.md").write_text("# Dot-claude memory\n\nMore project memory.\n")

        report = compute_budget(RepositoryContext(tmp_path))
        session_paths = {i.path for i in report.session_files}
        assert "CLAUDE.local.md" in session_paths
        assert ".claude/CLAUDE.md" in session_paths
        for path in ("CLAUDE.local.md", ".claude/CLAUDE.md"):
            item = next(i for i in report.session_files if i.path == path)
            assert item.harnesses == frozenset({"claude"})
            # The context-budget rule cannot see these files, so budget
            # must not attach a limit status to them.
            assert item.status is None

    def test_kiro_steering_inclusion_modes(self, tmp_path):
        steering = tmp_path / ".kiro" / "steering"
        steering.mkdir(parents=True)
        (steering / "product.md").write_text("# Product\n\nAlways-on product context.\n")
        (steering / "api.md").write_text(
            "---\ninclusion: fileMatch\nfileMatchPattern: 'app/api/**'\n---\n\n"
            "# API\n\nOnly when touching the API.\n"
        )
        (steering / "manual.md").write_text(
            "---\ninclusion: manual\n---\n\n# Manual\n\nOnly when referenced.\n"
        )

        report = compute_budget(RepositoryContext(tmp_path))
        session_paths = {i.path for i in report.session_files}
        on_demand_paths = {i.path for i in report.on_demand}
        assert ".kiro/steering/product.md" in session_paths
        assert ".kiro/steering/api.md" in on_demand_paths
        assert ".kiro/steering/manual.md" in on_demand_paths

    def test_instructions_md_without_applyto_is_conditional(self, tmp_path):
        instr = tmp_path / ".github" / "instructions"
        instr.mkdir(parents=True)
        (instr / "nokey.instructions.md").write_text(
            "---\ndescription: Reviewed manually\n---\n\nOnly applied when referenced.\n"
        )
        # Wrong-case key must still be honored.
        (instr / "lowercase.instructions.md").write_text(
            "---\napplyto: 'src/**'\n---\n\nScoped by a lower-cased key.\n"
        )
        (tmp_path / "AGENTS.md").write_text("# Guide\n\nGeneral instructions.\n")

        report = compute_budget(RepositoryContext(tmp_path))
        on_demand_paths = {i.path for i in report.on_demand}
        assert ".github/instructions/nokey.instructions.md" in on_demand_paths
        assert ".github/instructions/lowercase.instructions.md" in on_demand_paths

    def test_cursor_agent_requested_description_is_session_cost(self, tmp_path):
        repo = copy_fixture("budget/mixed", tmp_path)
        report = compute_budget(RepositoryContext(repo))

        desc = next(i for i in report.session_files if i.category == "cursor-rule-description")
        assert desc.path == ".cursor/rules/api-conventions.mdc"
        assert desc.tokens > 0
        assert desc.harnesses == frozenset({"cursor"})
        # The rule body itself stays on demand.
        assert ".cursor/rules/api-conventions.mdc" in {i.path for i in report.on_demand}

    def test_import_of_counted_file_unions_harnesses(self, tmp_path):
        # The docs-recommended pattern: CLAUDE.md is just an @AGENTS.md
        # import. AGENTS.md must not be double-billed, and the claude
        # session must include it.
        (tmp_path / "CLAUDE.md").write_text("# Claude\n\n@AGENTS.md\n")
        (tmp_path / "AGENTS.md").write_text(
            "# Agents\n\nRun make test before pushing. Keep handlers thin.\n"
        )
        report = compute_budget(RepositoryContext(tmp_path))

        agents_items = [i for i in report.session_files if i.path == "AGENTS.md"]
        assert len(agents_items) == 1
        assert "claude" in agents_items[0].harnesses
        assert "default" in agents_items[0].harnesses
        assert report.by_harness["claude"] >= agents_items[0].tokens

    def test_harness_filter(self, tmp_path):
        repo = copy_fixture("budget/mixed", tmp_path)
        claude = compute_budget(RepositoryContext(repo), harness="claude")
        paths = {i.path for i in claude.session_files}
        assert paths == {"CLAUDE.md", "docs/architecture.md", ".claude/rules/style.md"}
        assert claude.metadata  # claude sessions pay the descriptions tax

        # GEMINI.md exists, so AGENTS.md does not serve gemini sessions.
        gemini = compute_budget(RepositoryContext(repo), harness="gemini")
        paths = {i.path for i in gemini.session_files}
        assert paths == {"GEMINI.md"}
        assert gemini.metadata == []

        cursor = compute_budget(RepositoryContext(repo), harness="cursor")
        by_role = {(i.path, i.category) for i in cursor.session_files}
        assert by_role == {
            ("AGENTS.md", "agents-md"),
            (".cursor/rules/core-style.mdc", "instruction"),
            # Agent-requested rule: description is session cost for cursor.
            (".cursor/rules/api-conventions.mdc", "cursor-rule-description"),
        }
        assert cursor.metadata == []

        with pytest.raises(ValueError, match="Unknown harness"):
            compute_budget(RepositoryContext(repo), harness="emacs")

    def test_by_harness_totals(self, tmp_path):
        repo = copy_fixture("budget/mixed", tmp_path)
        report = compute_budget(RepositoryContext(repo))

        by_key = {(i.path, i.category): i.tokens for i in report.session_files}
        groups = {g.kind: g.total for g in report.metadata}
        # Claude Code lists skills, commands, and agents; a generic
        # AGENTS.md agent gets skills (agentskills.io) only.
        assert report.by_harness["claude"] == (
            by_key[("CLAUDE.md", "claude-md")]
            + by_key[("docs/architecture.md", "import")]
            + by_key[(".claude/rules/style.md", "rule")]
            + groups["skill"]
            + groups["command"]
            + groups["agent"]
        )
        assert report.by_harness["default"] == (
            by_key[("AGENTS.md", "agents-md")] + groups["skill"]
        )
        # GEMINI.md exists, so gemini sessions load it alone.
        assert report.by_harness["gemini"] == by_key[("GEMINI.md", "gemini-md")]

    def test_coderabbit_content_excluded_everywhere(self, tmp_path):
        repo = copy_fixture("budget/mixed", tmp_path)
        report = compute_budget(RepositoryContext(repo))

        all_paths = {i.path for i in report.session_files + report.on_demand}
        assert not any(".coderabbit" in (p or "") for p in all_paths)

    def test_category_sets_are_exact(self):
        # Guard against silent classification regressions: a category
        # removed from these sets changes bucket membership, so any edit
        # must be deliberate and update this test.
        assert SESSION_CATEGORIES == {
            "claude-md",
            "agents-md",
            "gemini-md",
            "instruction",
            "rule",
        }
        assert ON_DEMAND_CATEGORIES == {
            "skill",
            "skill-ref",
            "command",
            "agent",
            "prompt",
            "chatmode",
            "context",
            "extra",
        }
        assert EXCLUDED_CATEGORIES == {"coderabbit", "promptfoo-prompt"}

    def test_metadata_groups(self, tmp_path):
        repo = copy_fixture("budget/mixed", tmp_path)
        report = compute_budget(RepositoryContext(repo))

        groups = {g.kind: g for g in report.metadata}
        assert set(groups) == {"skill", "command", "agent"}
        assert [i.label for i in groups["skill"].items] == ["deploy-helper"]
        assert groups["skill"].items[0].tokens > 0
        # Commands without a frontmatter name fall back to the file stem;
        # disable-model-invocation commands are not listed in context.
        assert [i.label for i in groups["command"].items] == ["ship"]
        assert [i.label for i in groups["agent"].items] == ["reviewer"]
        # No limit category exists for agent descriptions.
        assert groups["agent"].items[0].status is None
        assert groups["skill"].items[0].status == "ok"

    def test_disable_model_invocation_excluded_from_metadata(self, tmp_path):
        repo = copy_fixture("budget/mixed", tmp_path)
        report = compute_budget(RepositoryContext(repo))

        commands = next(g for g in report.metadata if g.kind == "command")
        assert "scratch-notes" not in [i.label for i in commands.items]
        # The file body still costs on-demand tokens when the user invokes it.
        assert ".claude/commands/scratch-notes.md" in {i.path for i in report.on_demand}

    def test_agent_description_limits_never_flagged(self, tmp_path):
        # The context-budget rule enforces no agent-description limit, so
        # budget must not flag one even if a user configures it.
        repo = copy_fixture("budget/mixed", tmp_path)
        report = compute_budget(
            RepositoryContext(repo),
            user_limits={"agent-description": {"warn": 1, "error": 2}},
        )
        agents = next(g for g in report.metadata if g.kind == "agent")
        assert all(i.status is None for i in agents.items)

    def test_malformed_limits_degrade_to_defaults(self, tmp_path):
        repo = copy_fixture("budget/mixed", tmp_path)
        # Entirely non-dict limits are ignored; per-category garbage falls
        # back to the default threshold instead of crashing the report.
        report = compute_budget(RepositoryContext(repo), user_limits=5)
        assert report.limits["claude-md"] == (6000, 12000)

        report = compute_budget(
            RepositoryContext(repo),
            user_limits={"skill": {"warn": "heavy"}, "claude-md": {"warn": 10}},
        )
        assert report.limits["skill"] == (3000, 6000)  # garbage -> default
        assert report.limits["claude-md"] == (10, None)  # valid entry honored

    def test_unknown_category_priced_as_on_demand(self, tmp_path):
        # Plugin-contributed content blocks with novel categories must be
        # priced, not silently dropped.
        from skillsaw.blocks import FileContentBlock

        repo = copy_fixture("budget/mixed", tmp_path)
        (repo / "RUNBOOK.md").write_text("# Runbook\n\nRestart the worker.\n")
        context = RepositoryContext(repo)
        tree = context.lint_tree
        tree.children.append(FileContentBlock(path=repo / "RUNBOOK.md", category="runbook"))
        tree.invalidate_find_cache()

        report = compute_budget(context)
        runbook = next(i for i in report.on_demand if i.path == "RUNBOOK.md")
        assert runbook.category == "runbook"
        assert runbook.tokens > 0

    def test_symlinked_content_keeps_repo_relative_path(self, tmp_path):
        repo = copy_fixture("budget/mixed", tmp_path)
        target = tmp_path / "outside-target"
        target.mkdir()
        (target / "SKILL.md").write_text(
            "---\nname: linked-skill\ndescription: A skill reached through a symlink\n---\n\n"
            "# Linked Skill\n\nDo the linked thing carefully and report results.\n"
        )
        os.symlink(target, repo / ".claude" / "skills" / "linked-skill")

        report = compute_budget(RepositoryContext(repo))
        linked = [i for i in report.on_demand if "linked-skill" in (i.path or "")]
        assert linked, "symlinked skill missing from report"
        assert linked[0].path == ".claude/skills/linked-skill/SKILL.md"
        assert not linked[0].path.startswith("/")

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

    def test_no_duplicate_path_roles(self, tmp_path):
        repo = copy_fixture("budget/mixed", tmp_path)
        report = compute_budget(RepositoryContext(repo))

        # A path may appear once per role (whole file, import, description),
        # never twice in the same role.
        keys = [(i.path, i.category) for i in report.session_files + report.on_demand]
        assert len(keys) == len(set(keys))

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


class TestContextCli:
    @pytest.mark.integration
    def test_text_output(self, tmp_path):
        repo = copy_fixture("budget/mixed", tmp_path)
        result = run_context(repo)
        assert result.returncode == 0, result.stderr
        assert "SESSION START" in result.stdout
        assert "ON DEMAND" in result.stdout
        assert "CLAUDE.md" in result.stdout
        assert "skill descriptions (1)" in result.stdout

    @pytest.mark.integration
    def test_json_output(self, tmp_path):
        repo = copy_fixture("budget/mixed", tmp_path)
        result = run_context(repo, "--format", "json")
        assert result.returncode == 0, result.stderr

        payload = json.loads(result.stdout)
        assert payload["session_start"]["total_tokens"] > 0
        files = {f["path"] for f in payload["session_start"]["files"]}
        assert "CLAUDE.md" in files

    @pytest.mark.integration
    def test_top_truncates_text_output(self, tmp_path):
        repo = copy_fixture("budget/mixed", tmp_path)
        result = run_context(repo, "--top", "1")
        assert result.returncode == 0, result.stderr
        assert "top 1 of 8" in result.stdout
        assert "--top 0 for all" in result.stdout

    @pytest.mark.integration
    def test_window_changes_percentage(self, tmp_path):
        repo = copy_fixture("budget/mixed", tmp_path)
        result = run_context(repo, "--format", "json", "--window", "1000")
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
        result = run_context(repo, "--format", "json")
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
        result = run_context(repo)
        assert "over warn limit" in result.stdout
        assert "context-budget rule" in result.stdout

    @pytest.mark.integration
    def test_missing_path_exits_nonzero(self, tmp_path):
        result = run_context(tmp_path / "does-not-exist")
        assert result.returncode == 1
        assert "Path not found" in result.stderr


class TestBudgetItem:
    def test_to_dict_omits_empty_fields(self):
        item = BudgetItem(label="x", category="skill", tokens=5)
        assert item.to_dict() == {"label": "x", "category": "skill", "tokens": 5}

        full = BudgetItem(label="x", category="skill", tokens=5, path="a/b", status="ok")
        assert full.to_dict()["path"] == "a/b"
        assert full.to_dict()["status"] == "ok"

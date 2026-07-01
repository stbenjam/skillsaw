"""Integration tests: scaffold via CLI, then lint."""

import json
import subprocess
import sys

import yaml


def _run(*args):
    """Run a skillsaw CLI command and return the result."""
    result = subprocess.run(
        [sys.executable, "-m", "skillsaw", *args],
        capture_output=True,
        text=True,
    )
    return result


def _assert_lints_clean(root):
    """Assert a scaffolded directory produces zero violations of any severity.

    Regression guard: freshly scaffolded output must be clean under
    skillsaw's own rules — including info-level violations, which
    ``--strict`` alone would not catch.
    """
    r = _run("lint", "-v", "--strict", "--format", "json", str(root))
    assert r.returncode == 0, f"lint failed (exit {r.returncode}):\n{r.stdout}\n{r.stderr}"
    report = json.loads(r.stdout)
    assert (
        report["violations"] == []
    ), "scaffold should lint clean, found violations:\n" + "\n".join(
        f"  {v.get('rule_id')} [{v.get('file_path')}]: {v.get('message')}" for v in report["violations"]
    )


class TestMarketplaceScaffolding:
    """Create a marketplace from scratch via CLI and verify it lints clean."""

    def test_scaffold_and_lint(self, temp_dir):
        root = temp_dir / "my-marketplace"
        root.mkdir()

        # Create marketplace
        r = _run(
            "add",
            "marketplace",
            str(root),
            "--name",
            "test-mp",
            "--owner",
            "testuser",
            "--no-example-plugin",
        )
        assert r.returncode == 0, f"add marketplace failed:\n{r.stderr}"

        # Add a plugin
        r = _run("add", "plugin", "my-plugin", "--path", str(root))
        assert r.returncode == 0, f"add plugin failed:\n{r.stderr}"

        # Add a skill to the plugin
        r = _run(
            "add",
            "skill",
            "my-skill",
            "--plugin",
            "my-plugin",
            "--path",
            str(root),
        )
        assert r.returncode == 0, f"add skill failed:\n{r.stderr}"

        # Add a command to the plugin
        r = _run(
            "add",
            "command",
            "my-command",
            "--plugin",
            "my-plugin",
            "--path",
            str(root),
        )
        assert r.returncode == 0, f"add command failed:\n{r.stderr}"

        # Add an agent to the plugin
        r = _run(
            "add",
            "agent",
            "my-agent",
            "--plugin",
            "my-plugin",
            "--path",
            str(root),
        )
        assert r.returncode == 0, f"add agent failed:\n{r.stderr}"

        # Add a hook to the plugin
        r = _run(
            "add",
            "hook",
            "UserPromptSubmit",
            "--plugin",
            "my-plugin",
            "--path",
            str(root),
        )
        assert r.returncode == 0, f"add hook failed:\n{r.stderr}"

        # Lint the marketplace — must produce zero violations
        _assert_lints_clean(root)

    def test_scaffold_with_example_plugin(self, temp_dir):
        """Marketplace with the default example plugin should also lint clean."""
        root = temp_dir / "example-mp"
        root.mkdir()

        r = _run(
            "add",
            "marketplace",
            str(root),
            "--name",
            "example-mp",
            "--owner",
            "testuser",
        )
        assert r.returncode == 0, f"add marketplace failed:\n{r.stderr}"

        _assert_lints_clean(root)


class TestScaffoldLintsClean:
    """Scaffolded components must lint clean without a scaffolded config.

    The marketplace scaffold ships a `.skillsaw.yaml`; standalone and
    `.claude/` contexts do not, so these tests prove the templates
    themselves are clean under the default rule set.
    """

    def test_standalone_skill_lints_clean(self, temp_dir):
        r = _run("add", "skill", "data-export", "--path", str(temp_dir))
        assert r.returncode == 0, f"add skill failed:\n{r.stderr}"

        _assert_lints_clean(temp_dir)

    def test_dot_claude_components_lint_clean(self, temp_dir):
        (temp_dir / ".claude" / "skills").mkdir(parents=True)

        for args in (
            ("skill", "data-export"),
            ("command", "sync-data"),
            ("agent", "code-reviewer"),
            ("hook", "PreToolUse"),
        ):
            r = _run("add", *args, "--path", str(temp_dir))
            assert r.returncode == 0, f"add {args[0]} failed:\n{r.stderr}"

        _assert_lints_clean(temp_dir)


class TestStandaloneSkillCreation:
    """Create skills outside of any marketplace/plugin context."""

    def test_standalone_skill_in_empty_dir(self, temp_dir):
        """With no skills/ dir, creates <dir>/<name>/SKILL.md."""
        r = _run("add", "skill", "my-skill", "--path", str(temp_dir))
        assert r.returncode == 0, f"add skill failed:\n{r.stderr}"

        skill_md = temp_dir / "my-skill" / "SKILL.md"
        assert skill_md.exists()

        fm = yaml.safe_load(skill_md.read_text().split("---")[1])
        assert fm["name"] == "my-skill"

    def test_standalone_skill_prefers_skills_dir(self, temp_dir):
        """When skills/ exists, creates skills/<name>/SKILL.md."""
        (temp_dir / "skills").mkdir()

        r = _run("add", "skill", "my-skill", "--path", str(temp_dir))
        assert r.returncode == 0, f"add skill failed:\n{r.stderr}"

        assert (temp_dir / "skills" / "my-skill" / "SKILL.md").exists()
        assert not (temp_dir / "my-skill").exists()

    def test_standalone_skill_duplicate_errors(self, temp_dir):
        """Creating the same skill twice should fail."""
        r = _run("add", "skill", "dupe", "--path", str(temp_dir))
        assert r.returncode == 0

        r = _run("add", "skill", "dupe", "--path", str(temp_dir))
        assert r.returncode != 0
        assert "already exists" in r.stderr

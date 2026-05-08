"""Integration tests: scaffold via CLI, then lint."""

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

        # Lint the marketplace in strict mode — must pass
        r = _run("-v", "--strict", str(root))
        assert r.returncode == 0, f"lint failed (exit {r.returncode}):\n{r.stdout}\n{r.stderr}"

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

        r = _run("-v", "--strict", str(root))
        assert r.returncode == 0, f"lint failed (exit {r.returncode}):\n{r.stdout}\n{r.stderr}"


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

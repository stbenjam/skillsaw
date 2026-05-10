"""Tests for the skillsaw marketplace command group."""

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from skillsaw.marketplace.branding import (
    COLOR_PRESETS,
    DEFAULT_MARKETPLACE_TYPE,
    apply_branding,
    apply_replacements,
    build_replacements,
    get_color_scheme,
    load_template_config,
    read_template,
    write_template_config,
)
from skillsaw.marketplace.init import init_marketplace
from skillsaw.marketplace.add import (
    _find_plugin_context,
    _register_plugin,
    _resolve_plugin_dir,
    add_agent,
    add_command,
    add_hook,
    add_plugin,
    add_skill,
)

# ---------------------------------------------------------------------------
# Branding
# ---------------------------------------------------------------------------


class TestBranding:
    def test_get_color_scheme_valid(self):
        scheme = get_color_scheme("ocean-blue")
        assert scheme["primary"] == "#0077be"

    def test_get_color_scheme_invalid(self):
        with pytest.raises(ValueError, match="Unknown color scheme"):
            get_color_scheme("neon-pink")

    def test_read_template(self):
        content = read_template("marketplace.json")
        assert "{{MARKETPLACE_NAME}}" in content

    def test_read_template_with_type(self):
        content = read_template("plugin.json", "claude-code")
        assert "{{PLUGIN_NAME}}" in content

    def test_apply_replacements(self):
        result = apply_replacements("Hello {{NAME}}", {"NAME": "World"})
        assert result == "Hello World"

    def test_apply_replacements_no_double_substitution(self):
        """Values containing {{PLACEHOLDER}} patterns must not be substituted again."""
        result = apply_replacements(
            "name={{NAME}} owner={{OWNER}}",
            {"NAME": "{{OWNER}}", "OWNER": "alice"},
        )
        # NAME should become the literal string "{{OWNER}}", not "alice"
        assert result == "name={{OWNER}} owner=alice"

    def test_apply_replacements_empty(self):
        """An empty replacements dict should return the content unchanged."""
        assert apply_replacements("{{FOO}}", {}) == "{{FOO}}"

    def test_build_replacements(self):
        r = build_replacements("my-mp", "alice", "alice/my-mp", COLOR_PRESETS["ocean-blue"])
        assert r["MARKETPLACE_NAME"] == "my-mp"
        assert r["OWNER_NAME"] == "alice"
        assert r["GITHUB_PAGES_URL"] == "alice.github.io/my-mp"
        assert r["PRIMARY_COLOR"] == "#0077be"

    def test_template_config_roundtrip(self, temp_dir):
        write_template_config(
            temp_dir,
            name="test",
            owner="owner",
            github_repo="owner/test",
            color_scheme=COLOR_PRESETS["forest-green"],
            marketplace_type="claude-code",
        )
        config = load_template_config(temp_dir)
        assert config["marketplace_name"] == "test"
        assert config["marketplace_type"] == "claude-code"
        assert config["color_scheme"]["primary"] == "#228B22"

    def test_apply_branding_with_replacements(self, temp_dir):
        """apply_branding should substitute placeholders in branded files."""
        (temp_dir / "docs").mkdir()
        (temp_dir / "docs" / "index.html").write_text("<h1>{{MARKETPLACE_NAME}}</h1>")
        (temp_dir / "README.md").write_text("# {{OWNER_NAME}}")
        (temp_dir / ".claude-plugin").mkdir()
        (temp_dir / ".claude-plugin" / "marketplace.json").write_text(
            '{"name": "{{MARKETPLACE_NAME}}"}'
        )

        replacements = {"MARKETPLACE_NAME": "my-plugins", "OWNER_NAME": "alice"}
        apply_branding(temp_dir, replacements)

        assert "my-plugins" in (temp_dir / "docs" / "index.html").read_text()
        assert "alice" in (temp_dir / "README.md").read_text()
        assert "my-plugins" in (temp_dir / ".claude-plugin" / "marketplace.json").read_text()

    def test_apply_branding_from_config(self, temp_dir):
        """apply_branding without explicit replacements should load from .template-config.json."""
        write_template_config(
            temp_dir,
            name="auto-mp",
            owner="bob",
            github_repo="bob/auto-mp",
            color_scheme=COLOR_PRESETS["ocean-blue"],
            marketplace_type="claude-code",
        )
        (temp_dir / "docs").mkdir()
        (temp_dir / "docs" / "index.html").write_text("{{MARKETPLACE_NAME}}")
        (temp_dir / "README.md").write_text("{{OWNER_NAME}}")
        (temp_dir / ".claude-plugin").mkdir()
        (temp_dir / ".claude-plugin" / "marketplace.json").write_text(
            '{"name": "{{MARKETPLACE_NAME}}"}'
        )

        apply_branding(temp_dir)

        assert "auto-mp" in (temp_dir / "docs" / "index.html").read_text()
        assert "bob" in (temp_dir / "README.md").read_text()

    def test_apply_branding_no_config_is_noop(self, temp_dir):
        """apply_branding with no config and no replacements should be a no-op."""
        (temp_dir / "README.md").write_text("{{PLACEHOLDER}}")
        apply_branding(temp_dir)
        assert "{{PLACEHOLDER}}" in (temp_dir / "README.md").read_text()


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------


class TestInit:
    def test_init_creates_structure(self, temp_dir):
        root = temp_dir / "my-marketplace"
        root.mkdir()
        init_marketplace(
            path=root,
            name="test-mp",
            owner="testuser",
            no_example_plugin=True,
        )

        assert (root / ".claude-plugin" / "marketplace.json").exists()
        assert (root / ".claude-plugin" / "settings.json").exists()
        assert (root / "docs" / "index.html").exists()
        assert (root / "docs" / ".nojekyll").exists()
        assert (root / "README.md").exists()
        assert (root / "Makefile").exists()
        assert (root / ".github" / "workflows" / "lint.yml").exists()
        assert (root / ".skillsaw.yaml").exists()
        assert (root / ".gitignore").exists()
        assert (root / ".template-config.json").exists()

    def test_init_applies_branding(self, temp_dir):
        root = temp_dir / "branded"
        root.mkdir()
        init_marketplace(
            path=root,
            name="fancy-plugins",
            owner="alice",
            color_scheme="ocean-blue",
            no_example_plugin=True,
        )

        mp = json.loads((root / ".claude-plugin" / "marketplace.json").read_text())
        assert mp["name"] == "fancy-plugins"
        assert mp["owner"]["name"] == "alice"

        readme = (root / "README.md").read_text()
        assert "fancy-plugins" in readme

        html = (root / "docs" / "index.html").read_text()
        assert "#0077be" in html

    def test_init_with_example_plugin(self, temp_dir):
        root = temp_dir / "with-example"
        root.mkdir()
        init_marketplace(
            path=root,
            name="test-mp",
            owner="testuser",
        )

        assert (root / "plugins" / "example-plugin" / ".claude-plugin" / "plugin.json").exists()
        assert (root / "plugins" / "example-plugin" / "commands" / "example.md").exists()
        assert (root / "plugins" / "example-plugin" / "README.md").exists()

        mp = json.loads((root / ".claude-plugin" / "marketplace.json").read_text())
        plugin_names = [p["name"] for p in mp["plugins"]]
        assert "example-plugin" in plugin_names

    def test_init_stores_marketplace_type(self, temp_dir):
        root = temp_dir / "typed"
        root.mkdir()
        init_marketplace(
            path=root,
            name="test-mp",
            owner="testuser",
            marketplace_type="claude-code",
            no_example_plugin=True,
        )

        config = json.loads((root / ".template-config.json").read_text())
        assert config["marketplace_type"] == "claude-code"

    def test_init_rejects_existing(self, temp_dir):
        root = temp_dir / "existing"
        root.mkdir()
        (root / ".claude-plugin").mkdir()
        (root / ".claude-plugin" / "marketplace.json").write_text("{}")

        with pytest.raises(FileExistsError, match="already exists"):
            init_marketplace(path=root, name="test", owner="user")

    def test_init_default_github_repo(self, temp_dir):
        root = temp_dir / "defaults"
        root.mkdir()
        init_marketplace(
            path=root,
            name="my-plugins",
            owner="bob",
            no_example_plugin=True,
        )

        config = json.loads((root / ".template-config.json").read_text())
        assert config["github_repo"] == "bob/my-plugins"


# ---------------------------------------------------------------------------
# Add plugin
# ---------------------------------------------------------------------------


class TestAddPlugin:
    def _init_mp(self, temp_dir):
        root = temp_dir / "mp"
        root.mkdir()
        init_marketplace(path=root, name="test-mp", owner="testuser", no_example_plugin=True)
        return root

    def test_add_plugin(self, temp_dir):
        root = self._init_mp(temp_dir)
        result = add_plugin("my-plugin", path=root)

        assert result.exists()
        assert (result / ".claude-plugin" / "plugin.json").exists()
        assert (result / "commands" / "example.md").exists()
        assert (result / "README.md").exists()

        mp = json.loads((root / ".claude-plugin" / "marketplace.json").read_text())
        assert any(p["name"] == "my-plugin" for p in mp["plugins"])

        settings = json.loads((root / ".claude-plugin" / "settings.json").read_text())
        assert any(p["name"] == "my-plugin" for p in settings["installedPlugins"])

    def test_add_plugin_rejects_existing(self, temp_dir):
        root = self._init_mp(temp_dir)
        add_plugin("my-plugin", path=root)

        with pytest.raises(FileExistsError):
            add_plugin("my-plugin", path=root)

    def test_add_plugin_rejects_bad_name(self, temp_dir):
        root = self._init_mp(temp_dir)

        with pytest.raises(ValueError, match="kebab-case"):
            add_plugin("MyPlugin", path=root)

    def test_add_plugin_sets_owner_from_config(self, temp_dir):
        root = self._init_mp(temp_dir)
        result = add_plugin("owned-plugin", path=root)

        pj = json.loads((result / ".claude-plugin" / "plugin.json").read_text())
        assert pj["author"]["name"] == "testuser"


# ---------------------------------------------------------------------------
# Add skill / command / agent / hook
# ---------------------------------------------------------------------------


class TestAddComponents:
    def _init_with_plugin(self, temp_dir):
        root = temp_dir / "mp"
        root.mkdir()
        init_marketplace(path=root, name="test-mp", owner="testuser", no_example_plugin=True)
        add_plugin("my-plugin", path=root)
        return root

    def test_add_skill(self, temp_dir):
        root = self._init_with_plugin(temp_dir)
        result = add_skill("my-skill", "my-plugin", path=root)

        skill_md = result / "SKILL.md"
        assert skill_md.exists()
        content = skill_md.read_text()
        assert 'name: "my-skill"' in content
        assert "# My Skill" in content

    def test_add_command(self, temp_dir):
        root = self._init_with_plugin(temp_dir)
        result = add_command("greet", "my-plugin", path=root)

        assert result.exists()
        content = result.read_text()
        assert "my-plugin:greet" in content

    def test_add_agent(self, temp_dir):
        root = self._init_with_plugin(temp_dir)
        result = add_agent("helper", "my-plugin", path=root)

        assert result.exists()
        content = result.read_text()
        assert "subagent_type: helper" in content

    def test_add_hook(self, temp_dir):
        root = self._init_with_plugin(temp_dir)
        result = add_hook("PreToolUse", "my-plugin", path=root)

        assert result.exists()
        assert result.name == "PreToolUse.sh"
        content = result.read_text()
        assert "Hook: PreToolUse" in content

        hooks_json = result.parent / "hooks.json"
        assert hooks_json.exists()
        data = json.loads(hooks_json.read_text())
        assert "PreToolUse" in data["hooks"]
        assert data["hooks"]["PreToolUse"][0]["hooks"][0]["type"] == "command"

    def test_add_hook_rejects_invalid_event(self, temp_dir):
        root = self._init_with_plugin(temp_dir)

        with pytest.raises(ValueError, match="Unknown hook event"):
            add_hook("not-a-real-event", "my-plugin", path=root)

    def test_add_skill_rejects_missing_plugin(self, temp_dir):
        root = temp_dir / "mp"
        root.mkdir()
        init_marketplace(path=root, name="test-mp", owner="testuser", no_example_plugin=True)

        with pytest.raises(FileNotFoundError, match="not found in marketplace"):
            add_skill("my-skill", "nonexistent", path=root)

    def test_add_multiple_hooks_same_event_type(self, temp_dir):
        """Adding a second hook for a different event should not break hooks.json."""
        root = self._init_with_plugin(temp_dir)
        add_hook("PreToolUse", "my-plugin", path=root)
        add_hook("PostToolUse", "my-plugin", path=root)

        hooks_json = root / "plugins" / "my-plugin" / "hooks" / "hooks.json"
        data = json.loads(hooks_json.read_text())
        assert "PreToolUse" in data["hooks"]
        assert "PostToolUse" in data["hooks"]
        assert len(data["hooks"]["PreToolUse"]) == 1
        assert len(data["hooks"]["PostToolUse"]) == 1

    def test_add_hook_with_existing_empty_hooks_list(self, temp_dir):
        """Adding a hook when hooks.json has an entry with an empty 'hooks' list should not crash."""
        root = self._init_with_plugin(temp_dir)
        hooks_dir = root / "plugins" / "my-plugin" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        hooks_json = hooks_dir / "hooks.json"
        # Simulate a pre-existing entry with an empty hooks list
        hooks_json.write_text(
            json.dumps({"hooks": {"PreToolUse": [{"hooks": []}]}}, indent=2),
            encoding="utf-8",
        )

        result = add_hook("PreToolUse", "my-plugin", path=root)
        assert result.exists()

        data = json.loads(hooks_json.read_text())
        # The original empty entry should remain, and a new entry should be appended
        assert len(data["hooks"]["PreToolUse"]) == 2
        assert data["hooks"]["PreToolUse"][1]["hooks"][0]["type"] == "command"

    def test_add_command_rejects_duplicate(self, temp_dir):
        root = self._init_with_plugin(temp_dir)
        add_command("greet", "my-plugin", path=root)

        with pytest.raises(FileExistsError):
            add_command("greet", "my-plugin", path=root)


# ---------------------------------------------------------------------------
# Context detection
# ---------------------------------------------------------------------------


class TestContextDetection:
    def test_single_plugin_repo(self, temp_dir):
        """A repo with plugin.json but no marketplace.json should auto-detect."""
        root = temp_dir / "single"
        root.mkdir()
        (root / ".claude-plugin").mkdir()
        (root / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"name": "solo-plugin"}), encoding="utf-8"
        )
        (root / "skills").mkdir()

        found_root, plugin_dir, mp_type = _find_plugin_context(root, None)
        assert found_root == root.resolve()
        assert plugin_dir == root.resolve()

    def test_single_plugin_add_skill_no_plugin_flag(self, temp_dir):
        """Adding a skill to a single-plugin repo should not require --plugin."""
        root = temp_dir / "single"
        root.mkdir()
        (root / ".claude-plugin").mkdir()
        (root / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"name": "solo-plugin"}), encoding="utf-8"
        )
        (root / "skills").mkdir()

        result = add_skill("my-skill", plugin_name=None, path=root)
        assert result.exists()
        assert (result / "SKILL.md").exists()

    def test_marketplace_single_plugin_auto_select(self, temp_dir):
        """A marketplace with exactly one plugin should auto-select it."""
        root = temp_dir / "mp"
        root.mkdir()
        init_marketplace(path=root, name="test-mp", owner="testuser", no_example_plugin=True)
        add_plugin("only-plugin", path=root)

        _root, plugin_dir, _mp_type = _find_plugin_context(root, None)
        assert plugin_dir == (root / "plugins" / "only-plugin").resolve()

    def test_marketplace_no_plugins_raises(self, temp_dir):
        """A marketplace with zero plugins should raise FileNotFoundError, not ValueError."""
        root = temp_dir / "mp"
        root.mkdir()
        init_marketplace(path=root, name="test-mp", owner="testuser", no_example_plugin=True)

        with pytest.raises(FileNotFoundError, match="No plugins found"):
            _find_plugin_context(root, None)

    def test_marketplace_multi_plugin_requires_flag(self, temp_dir):
        """A marketplace with multiple plugins must specify --plugin."""
        root = temp_dir / "mp"
        root.mkdir()
        init_marketplace(path=root, name="test-mp", owner="testuser", no_example_plugin=True)
        add_plugin("plugin-a", path=root)
        add_plugin("plugin-b", path=root)

        with pytest.raises(ValueError, match="Multiple plugins"):
            _find_plugin_context(root, None)

    def test_marketplace_multi_plugin_with_flag(self, temp_dir):
        """Specifying --plugin resolves the correct plugin in a multi-plugin marketplace."""
        root = temp_dir / "mp"
        root.mkdir()
        init_marketplace(path=root, name="test-mp", owner="testuser", no_example_plugin=True)
        add_plugin("plugin-a", path=root)
        add_plugin("plugin-b", path=root)

        _root, plugin_dir, _mp_type = _find_plugin_context(root, "plugin-b")
        assert plugin_dir == (root / "plugins" / "plugin-b").resolve()

    def test_no_context_raises(self, temp_dir):
        """An empty directory should raise FileNotFoundError."""
        root = temp_dir / "empty"
        root.mkdir()

        with pytest.raises(FileNotFoundError, match="No plugin, marketplace, or .claude"):
            _find_plugin_context(root, None)

    def test_add_skill_cli_without_plugin_flag(self, temp_dir):
        """CLI should accept skill add without --plugin in a single-plugin marketplace."""
        root = temp_dir / "mp"
        root.mkdir()
        init_marketplace(path=root, name="test-mp", owner="testuser", no_example_plugin=True)
        add_plugin("only-plugin", path=root)

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "skillsaw",
                "add",
                "skill",
                "auto-skill",
                "--path",
                str(root),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Failed:\n{result.stdout}\n{result.stderr}"
        assert (root / "plugins" / "only-plugin" / "skills" / "auto-skill" / "SKILL.md").exists()

    def test_add_command_cli_without_plugin_flag(self, temp_dir):
        """CLI should accept command add without --plugin in a single-plugin marketplace."""
        root = temp_dir / "mp"
        root.mkdir()
        init_marketplace(path=root, name="test-mp", owner="testuser", no_example_plugin=True)
        add_plugin("only-plugin", path=root)

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "skillsaw",
                "add",
                "command",
                "auto-cmd",
                "--path",
                str(root),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Failed:\n{result.stdout}\n{result.stderr}"
        assert (root / "plugins" / "only-plugin" / "commands" / "auto-cmd.md").exists()

    def test_dot_claude_repo_detection(self, temp_dir):
        """A repo with .claude/ containing markers should be detected."""
        root = temp_dir / "dot-claude"
        root.mkdir()
        (root / ".claude" / "commands").mkdir(parents=True)

        found_root, plugin_dir, _mp_type = _find_plugin_context(root, None)
        assert found_root == root.resolve()
        assert plugin_dir == (root / ".claude").resolve()

    def test_dot_claude_add_skill(self, temp_dir):
        """Adding a skill to a .claude/ repo should place it in .claude/skills/."""
        root = temp_dir / "dot-claude"
        root.mkdir()
        (root / ".claude" / "commands").mkdir(parents=True)

        result = add_skill("my-skill", path=root)
        assert result.exists()
        assert (root / ".claude" / "skills" / "my-skill" / "SKILL.md").exists()

    def test_dot_claude_add_command(self, temp_dir):
        """Adding a command to a .claude/ repo should place it in .claude/commands/."""
        root = temp_dir / "dot-claude"
        root.mkdir()
        (root / ".claude" / "commands").mkdir(parents=True)

        result = add_command("greet", path=root)
        assert result.exists()
        assert (root / ".claude" / "commands" / "greet.md").exists()

    def test_dot_claude_add_agent(self, temp_dir):
        """Adding an agent to a .claude/ repo should place it in .claude/agents/."""
        root = temp_dir / "dot-claude"
        root.mkdir()
        (root / ".claude" / "skills").mkdir(parents=True)

        result = add_agent("helper", path=root)
        assert result.exists()
        assert (root / ".claude" / "agents" / "helper.md").exists()

    def test_dot_claude_add_hook(self, temp_dir):
        """Adding a hook to a .claude/ repo should place it in .claude/hooks/."""
        root = temp_dir / "dot-claude"
        root.mkdir()
        (root / ".claude" / "hooks").mkdir(parents=True)

        result = add_hook("PreToolUse", path=root)
        assert result.exists()
        assert (root / ".claude" / "hooks" / "PreToolUse.sh").exists()
        assert (root / ".claude" / "hooks" / "hooks.json").exists()

        data = json.loads((root / ".claude" / "hooks" / "hooks.json").read_text())
        assert "PreToolUse" in data["hooks"]

    def test_dot_claude_empty_not_detected(self, temp_dir):
        """A .claude/ dir with no markers should not be detected."""
        root = temp_dir / "no-markers"
        root.mkdir()
        (root / ".claude").mkdir()

        with pytest.raises(FileNotFoundError):
            _find_plugin_context(root, None)

    def test_dot_claude_cli_add_skill(self, temp_dir):
        """CLI skill add should work in a .claude/ repo without --plugin."""
        root = temp_dir / "dot-claude"
        root.mkdir()
        (root / ".claude" / "skills").mkdir(parents=True)

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "skillsaw",
                "add",
                "skill",
                "cli-skill",
                "--path",
                str(root),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Failed:\n{result.stdout}\n{result.stderr}"
        assert (root / ".claude" / "skills" / "cli-skill" / "SKILL.md").exists()


# ---------------------------------------------------------------------------
# Malformed marketplace.json
# ---------------------------------------------------------------------------


class TestMalformedMarketplaceJson:
    """Malformed marketplace.json must not crash with unhandled exceptions."""

    def _make_marketplace(self, temp_dir, plugins_value):
        """Create a minimal marketplace with a custom plugins value."""
        root = temp_dir / "mp"
        root.mkdir()
        (root / ".claude-plugin").mkdir()
        data = {"name": "test-mp", "owner": {"name": "testuser"}, "plugins": plugins_value}
        (root / ".claude-plugin" / "marketplace.json").write_text(
            json.dumps(data), encoding="utf-8"
        )
        return root

    # -- _find_plugin_context --------------------------------------------------

    def test_find_plugin_context_int_entry(self, temp_dir):
        """plugins: [42] should not raise TypeError."""
        root = self._make_marketplace(temp_dir, [42])
        with pytest.raises(FileNotFoundError, match="No plugins found"):
            _find_plugin_context(root, None)

    def test_find_plugin_context_null_entry(self, temp_dir):
        """plugins: [null] should not raise TypeError."""
        root = self._make_marketplace(temp_dir, [None])
        with pytest.raises(FileNotFoundError, match="No plugins found"):
            _find_plugin_context(root, None)

    def test_find_plugin_context_dict_missing_name(self, temp_dir):
        """plugins: [{"source": "./foo"}] should not raise KeyError."""
        root = self._make_marketplace(temp_dir, [{"source": "./foo"}])
        with pytest.raises(FileNotFoundError, match="No plugins found"):
            _find_plugin_context(root, None)

    def test_find_plugin_context_plugins_is_string(self, temp_dir):
        """plugins: "some-string" should raise ValueError, not iterate chars."""
        root = self._make_marketplace(temp_dir, "some-string")
        with pytest.raises(ValueError, match="must be a list"):
            _find_plugin_context(root, None)

    def test_find_plugin_context_valid_among_invalid(self, temp_dir):
        """One valid entry among invalid ones should auto-select."""
        root = self._make_marketplace(
            temp_dir,
            [42, None, {"source": "./foo"}, {"name": "good", "source": "./plugins/good"}],
        )
        # Create the plugin directory so _resolve_plugin_dir succeeds
        plugin_dir = root / "plugins" / "good"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / ".claude-plugin").mkdir()
        (plugin_dir / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"name": "good"}), encoding="utf-8"
        )

        _root, resolved_dir, _mp_type = _find_plugin_context(root, None)
        assert resolved_dir == plugin_dir.resolve()

    # -- _register_plugin ------------------------------------------------------

    def test_register_plugin_plugins_is_string(self, temp_dir):
        """_register_plugin should recover when plugins is a string."""
        root = self._make_marketplace(temp_dir, "bad")
        # Should not raise; should reset plugins to a list and add the entry
        _register_plugin(root, "new-plugin", "./plugins/new-plugin", "desc")

        data = json.loads(
            (root / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
        )
        assert isinstance(data["plugins"], list)
        assert any(p["name"] == "new-plugin" for p in data["plugins"])

    def test_register_plugin_skips_non_dict_entries(self, temp_dir):
        """_register_plugin should not crash on non-dict entries when checking duplicates."""
        root = self._make_marketplace(temp_dir, [42, None, {"name": "existing"}])
        _register_plugin(root, "new-plugin", "./plugins/new-plugin", "desc")

        data = json.loads(
            (root / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
        )
        names = [p["name"] for p in data["plugins"] if isinstance(p, dict)]
        assert "new-plugin" in names

    # -- _resolve_plugin_dir ---------------------------------------------------

    def test_resolve_plugin_dir_null_entries(self, temp_dir):
        """_resolve_plugin_dir should skip null entries without crashing."""
        root = self._make_marketplace(
            temp_dir,
            [None, {"name": "foo", "source": "./plugins/foo"}],
        )
        plugin_dir = root / "plugins" / "foo"
        plugin_dir.mkdir(parents=True)

        resolved = _resolve_plugin_dir(root, "foo")
        assert resolved == plugin_dir.resolve()

    def test_resolve_plugin_dir_int_entries(self, temp_dir):
        """_resolve_plugin_dir should skip int entries without crashing."""
        root = self._make_marketplace(temp_dir, [42, 0])
        with pytest.raises(FileNotFoundError, match="not found in marketplace"):
            _resolve_plugin_dir(root, "missing")

    def test_resolve_plugin_dir_dict_without_name(self, temp_dir):
        """_resolve_plugin_dir should skip entries without 'name' key."""
        root = self._make_marketplace(temp_dir, [{"source": "./bar"}])
        with pytest.raises(FileNotFoundError, match="not found in marketplace"):
            _resolve_plugin_dir(root, "bar")

    def test_resolve_plugin_dir_plugins_is_string(self, temp_dir):
        """_resolve_plugin_dir should raise ValueError when plugins is a string."""
        root = self._make_marketplace(temp_dir, "not-a-list")
        with pytest.raises(ValueError, match="must be a list"):
            _resolve_plugin_dir(root, "any-plugin")


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


class TestCLI:
    def test_add_help(self):
        result = subprocess.run(
            [sys.executable, "-m", "skillsaw", "add", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "marketplace" in result.stdout

    def test_add_marketplace_cli(self, temp_dir):
        root = temp_dir / "cli-test"
        root.mkdir()
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "skillsaw",
                "add",
                "marketplace",
                str(root),
                "--name",
                "cli-mp",
                "--owner",
                "cliuser",
                "--no-example-plugin",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert (root / ".claude-plugin" / "marketplace.json").exists()

    def test_add_plugin_cli(self, temp_dir):
        root = temp_dir / "cli-test"
        root.mkdir()
        init_marketplace(path=root, name="test-mp", owner="testuser", no_example_plugin=True)

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "skillsaw",
                "add",
                "plugin",
                "cli-plugin",
                "--path",
                str(root),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert (root / "plugins" / "cli-plugin").exists()

    def test_lint_generated_marketplace(self, temp_dir):
        """A generated marketplace should lint clean."""
        root = temp_dir / "lint-test"
        root.mkdir()
        init_marketplace(path=root, name="test-mp", owner="testuser")

        result = subprocess.run(
            [sys.executable, "-m", "skillsaw", str(root)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Lint failed:\n{result.stdout}\n{result.stderr}"


# ---------------------------------------------------------------------------
# Interactive mode
# ---------------------------------------------------------------------------


class TestInteractive:
    def test_marketplace_init_auto_interactive(self, temp_dir):
        """init_marketplace should auto-enable interactive when name/owner missing on a TTY."""
        root = temp_dir / "auto-int"
        root.mkdir()

        inputs = iter(["my-mp", "alice", "alice/my-mp", "1", "n"])
        with patch("builtins.input", side_effect=inputs):
            with patch("sys.stdin") as mock_stdin:
                mock_stdin.isatty.return_value = True
                init_marketplace(path=root)

        assert (root / ".claude-plugin" / "marketplace.json").exists()
        mp = json.loads((root / ".claude-plugin" / "marketplace.json").read_text())
        assert mp["name"] == "my-mp"

    def test_skill_prompts_for_name(self, temp_dir):
        """add_skill via CLI should prompt for name when missing on a TTY."""
        from skillsaw.marketplace.cli import _require_name

        with patch("builtins.input", return_value="prompted-skill"):
            with patch("sys.stdin") as mock_stdin:
                mock_stdin.isatty.return_value = True
                name = _require_name(None, "Skill name")

        assert name == "prompted-skill"

    def test_require_name_exits_non_tty(self):
        """_require_name should exit(1) when name is missing and stdin is not a TTY."""
        from skillsaw.marketplace.cli import _require_name

        with patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = False
            with pytest.raises(SystemExit):
                _require_name(None, "Skill name")

    def test_require_name_returns_provided(self):
        """_require_name should return the provided name without prompting."""
        from skillsaw.marketplace.cli import _require_name

        assert _require_name("my-name", "Skill name") == "my-name"

    def test_plugin_selection_prompt(self, temp_dir):
        """Multi-plugin marketplace should prompt for selection on a TTY."""
        root = temp_dir / "mp"
        root.mkdir()
        init_marketplace(path=root, name="test-mp", owner="testuser", no_example_plugin=True)
        add_plugin("alpha", path=root)
        add_plugin("beta", path=root)

        with patch("builtins.input", return_value="2"):
            with patch("sys.stdin") as mock_stdin:
                mock_stdin.isatty.return_value = True
                from skillsaw.marketplace.cli import _prompt_plugin_selection

                selected = _prompt_plugin_selection(root)

        assert selected == "beta"

    def test_plugin_selection_by_name(self, temp_dir):
        """Plugin selection should accept a name instead of a number."""
        root = temp_dir / "mp"
        root.mkdir()
        init_marketplace(path=root, name="test-mp", owner="testuser", no_example_plugin=True)
        add_plugin("alpha", path=root)
        add_plugin("beta", path=root)

        with patch("builtins.input", return_value="alpha"):
            from skillsaw.marketplace.cli import _prompt_plugin_selection

            selected = _prompt_plugin_selection(root)

        assert selected == "alpha"

    def test_multi_plugin_interactive_add_skill(self, temp_dir):
        """Adding a skill to a multi-plugin marketplace should prompt for plugin on TTY."""
        root = temp_dir / "mp"
        root.mkdir()
        init_marketplace(path=root, name="test-mp", owner="testuser", no_example_plugin=True)
        add_plugin("alpha", path=root)
        add_plugin("beta", path=root)

        with (
            patch("skillsaw.marketplace.cli.sys.stdin") as mock_stdin,
            patch("skillsaw.marketplace.cli.input", return_value="1"),
        ):
            mock_stdin.isatty.return_value = True
            from skillsaw.marketplace.cli import _handle_multi_plugin

            exc = ValueError("Multiple plugins in this marketplace. Use --plugin to specify.")
            _handle_multi_plugin(exc, add_skill, name="test-skill", path=root)

        assert (root / "plugins" / "alpha" / "skills" / "test-skill" / "SKILL.md").exists()

    def test_handle_multi_plugin_reraises_unrelated_error(self):
        """_handle_multi_plugin should re-raise errors that aren't about multiple plugins."""
        from skillsaw.marketplace.cli import _handle_multi_plugin

        exc = ValueError("Something completely different")
        with pytest.raises(ValueError, match="Something completely different"):
            _handle_multi_plugin(exc, add_skill, name="x", path=Path("/tmp"))

    def test_handle_multi_plugin_reraises_non_tty(self, temp_dir):
        """_handle_multi_plugin should re-raise even 'Multiple plugins' errors on non-TTY."""
        from skillsaw.marketplace.cli import _handle_multi_plugin

        exc = ValueError("Multiple plugins in this marketplace. Use --plugin to specify.")
        with patch("skillsaw.marketplace.cli.sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = False
            with pytest.raises(ValueError, match="Multiple plugins"):
                _handle_multi_plugin(exc, add_skill, name="x", path=temp_dir)

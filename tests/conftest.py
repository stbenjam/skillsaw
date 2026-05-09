"""
Pytest fixtures and configuration
"""

import json
import os
import pytest
from pathlib import Path
import tempfile
import shutil


def _load_dotenv():
    """Load .env file from project root if it exists."""
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            if not key:
                continue
            value = value.strip().strip("'\"")
            if key not in os.environ:
                os.environ[key] = value


_load_dotenv()


@pytest.fixture
def temp_dir():
    """Create a temporary directory for testing"""
    tmp = tempfile.mkdtemp()
    yield Path(tmp).resolve()
    shutil.rmtree(tmp)


@pytest.fixture
def valid_plugin(temp_dir):
    """Create a valid plugin structure"""
    plugin_dir = temp_dir / "test-plugin"
    plugin_dir.mkdir()

    # Create .claude-plugin/plugin.json
    claude_dir = plugin_dir / ".claude-plugin"
    claude_dir.mkdir()

    plugin_json = {
        "name": "test-plugin",
        "description": "A test plugin",
        "version": "1.0.0",
        "author": {"name": "Test Author"},
    }

    with open(claude_dir / "plugin.json", "w") as f:
        json.dump(plugin_json, f)

    # Create commands directory with a valid command
    commands_dir = plugin_dir / "commands"
    commands_dir.mkdir()

    command_content = """---
description: A test command
---

## Name
test-plugin:test-command

## Synopsis
```
/test-plugin:test-command [args]
```

## Description
This is a test command.

## Implementation
1. Do something
2. Return result
"""

    with open(commands_dir / "test-command.md", "w") as f:
        f.write(command_content)

    # Create README
    with open(plugin_dir / "README.md", "w") as f:
        f.write("# Test Plugin\n\nA test plugin for testing.")

    return plugin_dir


@pytest.fixture
def marketplace_repo(temp_dir):
    """Create a marketplace repository structure"""
    # Create marketplace.json
    claude_dir = temp_dir / ".claude-plugin"
    claude_dir.mkdir()

    marketplace_json = {
        "name": "test-marketplace",
        "owner": {"name": "Test Owner"},
        "plugins": [
            {"name": "plugin-one", "source": "./plugins/plugin-one", "description": "First plugin"},
            {
                "name": "plugin-two",
                "source": "./plugins/plugin-two",
                "description": "Second plugin",
            },
        ],
    }

    with open(claude_dir / "marketplace.json", "w") as f:
        json.dump(marketplace_json, f)

    # Create plugins directory
    plugins_dir = temp_dir / "plugins"
    plugins_dir.mkdir()

    # Create two plugins
    for plugin_name in ["plugin-one", "plugin-two"]:
        plugin_dir = plugins_dir / plugin_name
        plugin_dir.mkdir()

        # Create plugin.json
        plugin_claude_dir = plugin_dir / ".claude-plugin"
        plugin_claude_dir.mkdir()

        plugin_json = {
            "name": plugin_name,
            "description": f"Test {plugin_name}",
            "version": "1.0.0",
            "author": {"name": "Test Author"},
        }

        with open(plugin_claude_dir / "plugin.json", "w") as f:
            json.dump(plugin_json, f)

        # Create commands
        commands_dir = plugin_dir / "commands"
        commands_dir.mkdir()

        with open(commands_dir / "test.md", "w") as f:
            f.write(f"""---
description: Test command
---

## Name
{plugin_name}:test

## Synopsis
```
/{plugin_name}:test
```

## Description
Test command

## Implementation
Do something
""")

    return temp_dir


@pytest.fixture
def flat_structure_marketplace(temp_dir):
    """Create a marketplace with a flat structure plugin (source: './')"""
    # Create marketplace.json
    claude_dir = temp_dir / ".claude-plugin"
    claude_dir.mkdir()

    marketplace_json = {
        "name": "flat-marketplace",
        "owner": {"name": "Test Owner"},
        "plugins": [
            {
                "name": "flat-plugin",
                "source": "./",
                "description": "Plugin at repository root",
                "strict": False,
            }
        ],
    }

    with open(claude_dir / "marketplace.json", "w") as f:
        json.dump(marketplace_json, f)

    # Create commands at root level
    commands_dir = temp_dir / "commands"
    commands_dir.mkdir()

    with open(commands_dir / "test.md", "w") as f:
        f.write("""---
description: Test command
---

## Name
flat-plugin:test

## Synopsis
```
/flat-plugin:test
```

## Description
Test command for flat structure

## Implementation
Do something
""")

    # Create skills at root level
    skills_dir = temp_dir / "skills"
    skills_dir.mkdir()
    skill_dir = skills_dir / "test-skill"
    skill_dir.mkdir()

    with open(skill_dir / "SKILL.md", "w") as f:
        f.write("""---
description: Test skill
---

# Test Skill

This is a test skill for flat structure.
""")

    return temp_dir


@pytest.fixture
def custom_path_marketplace(temp_dir):
    """Create a marketplace with custom plugin paths"""
    # Create marketplace.json
    claude_dir = temp_dir / ".claude-plugin"
    claude_dir.mkdir()

    marketplace_json = {
        "name": "custom-path-marketplace",
        "owner": {"name": "Test Owner"},
        "plugins": [
            {
                "name": "custom-plugin",
                "source": "./custom/my-plugin",
                "description": "Plugin in custom directory",
            }
        ],
    }

    with open(claude_dir / "marketplace.json", "w") as f:
        json.dump(marketplace_json, f)

    # Create plugin in custom directory
    custom_dir = temp_dir / "custom" / "my-plugin"
    custom_dir.mkdir(parents=True)

    # Create plugin.json
    plugin_claude_dir = custom_dir / ".claude-plugin"
    plugin_claude_dir.mkdir()

    plugin_json = {
        "name": "custom-plugin",
        "description": "Test custom path plugin",
        "version": "1.0.0",
        "author": {"name": "Test Author"},
    }

    with open(plugin_claude_dir / "plugin.json", "w") as f:
        json.dump(plugin_json, f)

    # Create commands
    commands_dir = custom_dir / "commands"
    commands_dir.mkdir()

    with open(commands_dir / "test.md", "w") as f:
        f.write("""---
description: Test command
---

## Name
custom-plugin:test

## Synopsis
```
/custom-plugin:test
```

## Description
Test command

## Implementation
Do something
""")

    return temp_dir


@pytest.fixture
def strict_false_marketplace(temp_dir):
    """Create a marketplace with strict: false and no plugin.json"""
    # Create marketplace.json
    claude_dir = temp_dir / ".claude-plugin"
    claude_dir.mkdir()

    marketplace_json = {
        "name": "strict-false-marketplace",
        "owner": {"name": "Test Owner"},
        "plugins": [
            {
                "name": "no-manifest-plugin",
                "source": "./my-plugin",
                "description": "Plugin without plugin.json",
                "version": "2.0.0",
                "author": {"name": "Marketplace Author"},
                "strict": False,
                "commands": ["./commands/"],
                "skills": ["./skills/"],
            }
        ],
    }

    with open(claude_dir / "marketplace.json", "w") as f:
        json.dump(marketplace_json, f)

    # Create plugin directory WITHOUT .claude-plugin/plugin.json
    plugin_dir = temp_dir / "my-plugin"
    plugin_dir.mkdir()

    # Create commands
    commands_dir = plugin_dir / "commands"
    commands_dir.mkdir()

    with open(commands_dir / "test.md", "w") as f:
        f.write("""---
description: Test command
---

## Name
no-manifest-plugin:test

## Synopsis
```
/no-manifest-plugin:test
```

## Description
Test command without plugin.json

## Implementation
Do something
""")

    # Create skills
    skills_dir = plugin_dir / "skills"
    skills_dir.mkdir()
    skill_dir = skills_dir / "test-skill"
    skill_dir.mkdir()

    with open(skill_dir / "SKILL.md", "w") as f:
        f.write("""---
description: Test skill
---

# Test Skill

This is a test skill without plugin.json.
""")

    return temp_dir


@pytest.fixture
def mixed_marketplace(temp_dir):
    """Create a marketplace with both plugins/ directory and marketplace sources"""
    # Create marketplace.json
    claude_dir = temp_dir / ".claude-plugin"
    claude_dir.mkdir()

    marketplace_json = {
        "name": "mixed-marketplace",
        "owner": {"name": "Test Owner"},
        "plugins": [
            {
                "name": "marketplace-plugin",
                "source": "./custom/marketplace-plugin",
                "description": "Plugin defined in marketplace",
            },
            {
                "name": "plugins-dir-plugin",
                "source": "./plugins/plugins-dir-plugin",
                "description": "Plugin in plugins/ directory",
            },
        ],
    }

    with open(claude_dir / "marketplace.json", "w") as f:
        json.dump(marketplace_json, f)

    # Create plugin in custom directory
    custom_dir = temp_dir / "custom" / "marketplace-plugin"
    custom_dir.mkdir(parents=True)

    custom_claude_dir = custom_dir / ".claude-plugin"
    custom_claude_dir.mkdir()

    with open(custom_claude_dir / "plugin.json", "w") as f:
        json.dump({"name": "marketplace-plugin"}, f)

    custom_commands = custom_dir / "commands"
    custom_commands.mkdir()

    with open(custom_commands / "test.md", "w") as f:
        f.write("---\ndescription: Test\n---\n# Test")

    # Create plugin in plugins/ directory
    plugins_dir = temp_dir / "plugins"
    plugins_dir.mkdir()

    plugin_dir = plugins_dir / "plugins-dir-plugin"
    plugin_dir.mkdir()

    plugin_claude_dir = plugin_dir / ".claude-plugin"
    plugin_claude_dir.mkdir()

    with open(plugin_claude_dir / "plugin.json", "w") as f:
        json.dump({"name": "plugins-dir-plugin"}, f)

    plugin_commands = plugin_dir / "commands"
    plugin_commands.mkdir()

    with open(plugin_commands / "test.md", "w") as f:
        f.write("---\ndescription: Test\n---\n# Test")

    return temp_dir


@pytest.fixture
def remote_source_marketplace(temp_dir):
    """Create a marketplace with remote plugin sources"""
    # Create marketplace.json
    claude_dir = temp_dir / ".claude-plugin"
    claude_dir.mkdir()

    marketplace_json = {
        "name": "remote-marketplace",
        "owner": {"name": "Test Owner"},
        "plugins": [
            {
                "name": "github-plugin",
                "source": {"source": "github", "repo": "owner/repo"},
                "description": "Plugin from GitHub",
            },
            {
                "name": "git-plugin",
                "source": {"source": "url", "url": "https://git.example.com/plugin.git"},
                "description": "Plugin from git URL",
            },
        ],
    }

    with open(claude_dir / "marketplace.json", "w") as f:
        json.dump(marketplace_json, f)

    return temp_dir

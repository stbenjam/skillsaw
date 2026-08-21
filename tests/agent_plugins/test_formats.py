"""Version registry tests for the Agent Plugins format helpers."""

import pytest

from skillsaw.formats.agent_plugins import (
    SUPPORTED_AGENT_PLUGIN_SCHEMA_VERSIONS,
    agent_plugin_schema_id,
    load_agent_plugin_schema,
    supported_agent_plugin_schema_version,
)


@pytest.mark.parametrize("version", SUPPORTED_AGENT_PLUGIN_SCHEMA_VERSIONS)
@pytest.mark.parametrize("kind", ["plugin", "mcp"])
def test_supported_schema_ids_match_the_bundled_documents(version, kind):
    schema_id = agent_plugin_schema_id(version, kind)
    schema = load_agent_plugin_schema(f"{kind}.schema.json", version)

    assert schema["$id"] == schema_id
    assert schema["properties"]["$schema"]["const"] == schema_id
    assert supported_agent_plugin_schema_version(schema_id, kind) == version


def test_schema_id_rejects_an_unsupported_version():
    with pytest.raises(ValueError, match="schema version"):
        agent_plugin_schema_id("9.9.9", "plugin")


def test_schema_id_rejects_an_unsupported_kind():
    with pytest.raises(ValueError, match="schema kind"):
        agent_plugin_schema_id("1.1.0", "hooks")


def test_schema_loader_rejects_an_unsupported_version():
    with pytest.raises(ValueError, match="schema version"):
        load_agent_plugin_schema("plugin.schema.json", "9.9.9")

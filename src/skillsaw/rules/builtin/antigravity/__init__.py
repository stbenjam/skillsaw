"""
Rules for Google Antigravity workspace configuration and plugins.

Antigravity reads ``AGENTS.md`` for portable instructions and loads Agent
Skills from ``<customization root>/skills/``, both supported by skillsaw's
universal rules. The Antigravity-specific rules in this package validate
what only ``agy`` reads: lifecycle hooks in ``hooks.json``, MCP servers in
``mcp_config.json``, plugin manifests in ``plugins/<name>/plugin.json``,
and the registry files that name where else to load customizations from.

Every verdict here is measured against ``agy`` 1.1.25 rather than read off
the documentation; ``skillsaw.formats.antigravity`` records the method and
what it could not reach.

No import list: ``BUILTIN_RULES`` walks this package, so a rule registers
itself by existing.
"""

"""Validate Kiro MCP field shapes; shared rules own security policy."""

from skillsaw.blocks.kiro import KiroInlineMcpBlock, KiroMcpBlock
from skillsaw.context import RepositoryType
from skillsaw.diagnostics import safe_display
from skillsaw.formats.kiro import mcp_field_problems
from skillsaw.rule import Rule, Severity


class KiroMcpValidRule(Rule):
    """A conservative subset allowing partial overlays and legacy records."""

    since = "0.21.1"
    default_enabled = False
    repo_types = frozenset({RepositoryType.KIRO})

    @property
    def rule_id(self):
        return "kiro-mcp-valid"

    @property
    def description(self):
        return "Kiro workspace and agent MCP entries must use documented field types"

    def default_severity(self):
        return Severity.ERROR

    def check(self, context):
        violations = []
        for block_type in (KiroMcpBlock, KiroInlineMcpBlock):
            for block in context.lint_tree.find(block_type):
                data = block.raw_data
                if block.parse_error or data is None:
                    violations.append(
                        self.violation(
                            "Kiro MCP configuration must be a JSON object with valid syntax",
                            file_path=block.path,
                        )
                    )
                    continue
                if not data:
                    continue
                servers = data.get("mcpServers")
                if not isinstance(servers, dict):
                    violations.append(
                        self.violation(
                            "Kiro MCP configuration must contain an 'mcpServers' object",
                            file_path=block.path,
                        )
                    )
                    continue
                for name, server in servers.items():
                    shown = safe_display(str(name))
                    if not isinstance(server, dict):
                        problems = [(name, f"MCP server '{shown}' must be an object")]
                        source = servers
                    else:
                        problems = [
                            (key, f"MCP server '{shown}': {message}")
                            for key, message in mcp_field_problems(server)
                        ]
                        source = server
                    for key, message in problems:
                        line = (
                            block.source_line_for(source, key)
                            if isinstance(block, KiroInlineMcpBlock)
                            else None
                        )
                        violations.append(self.violation(message, file_path=block.path, line=line))
        return violations

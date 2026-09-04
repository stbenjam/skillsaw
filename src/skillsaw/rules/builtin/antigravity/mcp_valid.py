"""Rule: antigravity-mcp-valid."""

from __future__ import annotations

import math
from typing import List

from skillsaw.blocks import AntigravityMcpBlock
from skillsaw.context import RepositoryContext
from skillsaw.diagnostics import safe_display
from skillsaw.repository_types import RepositoryType
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.rules.builtin.secret_detection import url_has_userinfo


class AntigravityMcpValidRule(Rule):
    """Validate Antigravity mcp_config.json configuration."""

    default_enabled = True
    repo_types = frozenset({RepositoryType.ANTIGRAVITY_PLUGIN, RepositoryType.ANTIGRAVITY})

    @property
    def rule_id(self) -> str:
        return "antigravity-mcp-valid"

    @property
    def description(self) -> str:
        return (
            "Antigravity mcp_config.json must declare valid MCP server configurations "
            "with supported transports ('serverUrl' or 'command')"
        )

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        for block in context.lint_tree.find(AntigravityMcpBlock):
            if block.parse_error is not None:
                violations.append(
                    self.violation(
                        f"Invalid JSON: {safe_display(block.parse_error)}",
                        file_path=block.path,
                        fingerprint_discriminator=block.parse_error,
                    )
                )
                continue

            found = block.first_non_finite()
            if found is not None:
                non_path, _val = found
                violations.append(
                    self.violation(
                        f"JSON standard forbids non-finite number at {non_path}",
                        file_path=block.path,
                        fingerprint_discriminator=non_path,
                    )
                )
                continue

            data = block.raw_data
            if not isinstance(data, dict):
                violations.append(
                    self.violation(
                        "Antigravity MCP configuration must be an object",
                        file_path=block.path,
                    )
                )
                continue

            if "mcpServers" not in data:
                continue

            mcp_servers = data["mcpServers"]
            if not isinstance(mcp_servers, dict):
                violations.append(
                    self.violation(
                        "'mcpServers' must be an object",
                        file_path=block.path,
                    )
                )
                continue

            for server_name, server in mcp_servers.items():
                shown = safe_display(server_name)
                if not isinstance(server, dict):
                    violations.append(
                        self.violation(
                            f"MCP server '{shown}' configuration must be an object",
                            file_path=block.path,
                        )
                    )
                    continue

                # Connection check
                if "serverUrl" in server:
                    server_url = server["serverUrl"]
                    if not isinstance(server_url, str) or not server_url.strip():
                        violations.append(
                            self.violation(
                                f"MCP server '{shown}' 'serverUrl' must be a non-empty string",
                                file_path=block.path,
                            )
                        )
                    elif url_has_userinfo(server_url):
                        violations.append(
                            self.violation(
                                f"MCP server '{shown}' 'serverUrl' must not contain user information",
                                file_path=block.path,
                            )
                        )

                    if "headers" in server and not isinstance(server["headers"], dict):
                        violations.append(
                            self.violation(
                                f"MCP server '{shown}' 'headers' must be an object",
                                file_path=block.path,
                            )
                        )
                elif "command" in server:
                    command = server["command"]
                    if not isinstance(command, str) or not command.strip():
                        violations.append(
                            self.violation(
                                f"MCP server '{shown}' 'command' must be a non-empty string",
                                file_path=block.path,
                            )
                        )

                    if "args" in server:
                        args = server["args"]
                        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
                            violations.append(
                                self.violation(
                                    f"MCP server '{shown}' 'args' must be an array of strings",
                                    file_path=block.path,
                                )
                            )

                    if "env" in server and not isinstance(server["env"], dict):
                        violations.append(
                            self.violation(
                                f"MCP server '{shown}' 'env' must be an object",
                                file_path=block.path,
                            )
                        )
                else:
                    unsupported = [f for f in ("url", "httpUrl") if f in server]
                    if unsupported:
                        for field in unsupported:
                            violations.append(
                                self.violation(
                                    f"MCP server '{shown}' uses unsupported '{field}'; Antigravity requires 'serverUrl'",
                                    file_path=block.path,
                                )
                            )
                    else:
                        violations.append(
                            self.violation(
                                f"MCP server '{shown}' must specify either 'serverUrl' (for remote servers) or 'command' (for local servers)",
                                file_path=block.path,
                            )
                        )

                # Timeout check
                if "timeout" in server:
                    timeout = server["timeout"]
                    if (
                        isinstance(timeout, bool)
                        or not isinstance(timeout, (int, float))
                        or not math.isfinite(timeout)
                        or timeout <= 0
                    ):
                        violations.append(
                            self.violation(
                                f"MCP server '{shown}' 'timeout' must be a positive number",
                                file_path=block.path,
                            )
                        )

        return violations

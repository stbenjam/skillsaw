"""
Rules for validating MCP (Model Context Protocol) configuration
"""

from .valid_json import McpValidJsonRule
from .prohibited import McpProhibitedRule

__all__ = [
    "McpValidJsonRule",
    "McpProhibitedRule",
]

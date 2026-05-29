"""
Rules for validating plugin structure
"""

from .json_required import PluginJsonRequiredRule
from .json_valid import PluginJsonValidRule
from .naming import PluginNamingRule
from .readme import PluginReadmeRule

__all__ = [
    "PluginJsonRequiredRule",
    "PluginJsonValidRule",
    "PluginNamingRule",
    "PluginReadmeRule",
]

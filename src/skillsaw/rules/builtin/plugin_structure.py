"""Backward-compatibility shim — rules moved to plugins/ package."""

from .plugins import (  # noqa: F401
    PluginJsonRequiredRule,
    PluginJsonValidRule,
    PluginNamingRule,
    PluginReadmeRule,
)

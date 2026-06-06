"""Backward-compatibility shim — rules moved to commands/ package."""

from .commands import (  # noqa: F401
    CommandNamingRule,
    CommandFrontmatterRule,
    CommandSectionsRule,
    CommandNameFormatRule,
)

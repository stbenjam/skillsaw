"""Backward-compatibility shim — rules moved to instructions/ package."""

from .instructions import (  # noqa: F401
    InstructionFileValidRule,
    InstructionImportsValidRule,
)

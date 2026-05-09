"""LLM-as-judge autofix engine using LiteLLM."""

from .engine import LLMEngine, EngineConfig, LLMResult, ToolCallRecord, TokenUsage
from .tools import (
    LLMTool,
    ReadFileTool,
    WriteFileTool,
    ReplaceSectionTool,
    LintTool,
    DiffTool,
)
from ._litellm import LiteLLMProvider, CompletionResult, ToolCall

__all__ = [
    "LLMEngine",
    "EngineConfig",
    "LLMResult",
    "ToolCallRecord",
    "TokenUsage",
    "LLMTool",
    "ReadFileTool",
    "WriteFileTool",
    "ReplaceSectionTool",
    "LintTool",
    "DiffTool",
    "LiteLLMProvider",
    "CompletionResult",
    "ToolCall",
]

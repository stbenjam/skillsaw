"""LiteLLM wrapper — isolates the dependency behind a seam."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass
class CompletionResult:
    content: Optional[str]
    tool_calls: List[ToolCall]
    usage: TokenUsage


class CompletionProvider(Protocol):
    def complete(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        model: str,
        max_tokens: int = 4096,
    ) -> CompletionResult: ...


def _get_litellm():
    try:
        import litellm

        return litellm
    except ImportError:
        raise ImportError("LLM features require litellm. Install with: pip install skillsaw[llm]")


class LiteLLMProvider:
    """Production CompletionProvider backed by LiteLLM."""

    def complete(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        model: str,
        max_tokens: int = 4096,
    ) -> CompletionResult:
        litellm = _get_litellm()

        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = tools

        response = litellm.completion(**kwargs)
        choice = response.choices[0]
        message = choice.message

        tool_calls: List[ToolCall] = []
        if message.tool_calls:
            import json

            for tc in message.tool_calls:
                args = tc.function.arguments
                if isinstance(args, str):
                    args = json.loads(args)
                tool_calls.append(
                    ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=args,
                    )
                )

        usage_info = response.usage
        usage = TokenUsage(
            prompt_tokens=usage_info.prompt_tokens or 0,
            completion_tokens=usage_info.completion_tokens or 0,
        )

        return CompletionResult(
            content=message.content,
            tool_calls=tool_calls,
            usage=usage,
        )

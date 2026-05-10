"""LLMEngine — conversation loop, tool dispatch, retries."""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from ._litellm import CompletionProvider, CompletionResult, ToolCall, TokenUsage


@dataclass
class ToolCallRecord:
    name: str
    arguments: Dict[str, Any]
    result: str


@dataclass
class LLMResult:
    text: Optional[str]
    usage: TokenUsage
    tool_calls: List[ToolCallRecord]
    iterations: int
    budget_exhausted: bool


class LLMEngine:
    def __init__(
        self,
        provider: CompletionProvider,
        tools: list,
        *,
        model: str = "",
        max_iterations: int = 5,
        max_tokens: int = 500_000,
        on_event: Optional[Any] = None,
    ):
        self._provider = provider
        self._tools = {t.name: t for t in tools}
        self._model = model
        self._max_iterations = max_iterations
        self._max_tokens = max_tokens
        self._on_event = on_event
        self._messages: List[Dict[str, Any]] = []
        self._total_usage = TokenUsage(0, 0)

    def _tool_schemas(self) -> List[Dict[str, Any]]:
        schemas = []
        for tool in self._tools.values():
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
            )
        return schemas

    def _dispatch_tool(self, call: ToolCall) -> str:
        tool = self._tools.get(call.name)
        if tool is None:
            return f"Error: unknown tool '{call.name}'"
        try:
            return tool.execute(**call.arguments)
        except Exception as e:
            return f"Error executing {call.name}: {e}"

    def run(self, system_prompt: str, user_message: str) -> LLMResult:
        self._messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]
        self._total_usage = TokenUsage(0, 0)
        all_tool_calls: List[ToolCallRecord] = []
        tool_schemas = self._tool_schemas()
        iterations = 0

        for _ in range(self._max_iterations):
            iterations += 1
            logger.debug("Iteration %d/%d", iterations, self._max_iterations)
            if self._on_event:
                self._on_event(
                    "iteration",
                    iteration=iterations,
                    max_iterations=self._max_iterations,
                )
            total_tokens = self._total_usage.prompt_tokens + self._total_usage.completion_tokens
            if total_tokens >= self._max_tokens:
                return LLMResult(
                    text=None,
                    usage=self._total_usage,
                    tool_calls=all_tool_calls,
                    iterations=iterations,
                    budget_exhausted=True,
                )

            try:
                result = self._provider.complete(
                    messages=self._messages,
                    tools=tool_schemas,
                    model=self._model,
                    max_tokens=4096,
                )
            except Exception as e:
                print(f"LLM API error: {e}", file=sys.stderr)
                return LLMResult(
                    text=None,
                    usage=self._total_usage,
                    tool_calls=all_tool_calls,
                    iterations=iterations,
                    budget_exhausted=False,
                )

            if result.usage:
                self._total_usage.prompt_tokens += result.usage.prompt_tokens
                self._total_usage.completion_tokens += result.usage.completion_tokens

            if not result.tool_calls:
                return LLMResult(
                    text=result.content,
                    usage=self._total_usage,
                    tool_calls=all_tool_calls,
                    iterations=iterations,
                    budget_exhausted=False,
                )

            assistant_msg: Dict[str, Any] = {"role": "assistant"}
            if result.content:
                assistant_msg["content"] = result.content
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": (
                            tc.arguments
                            if isinstance(tc.arguments, str)
                            else json.dumps(tc.arguments)
                        ),
                    },
                }
                for tc in result.tool_calls
            ]
            self._messages.append(assistant_msg)

            for tc in result.tool_calls:
                args_dict = tc.arguments if isinstance(tc.arguments, dict) else {}
                logger.debug(
                    "  Tool: %s(%s)",
                    tc.name,
                    ", ".join(f"{k}={v!r}" for k, v in args_dict.items()),
                )
                if self._on_event:
                    self._on_event("tool_call", name=tc.name, arguments=args_dict)
                tool_result = self._dispatch_tool(tc)
                all_tool_calls.append(
                    ToolCallRecord(
                        name=tc.name,
                        arguments=tc.arguments,
                        result=tool_result,
                    )
                )
                self._messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )

        return LLMResult(
            text=None,
            usage=self._total_usage,
            tool_calls=all_tool_calls,
            iterations=iterations,
            budget_exhausted=False,
        )

"""Shared helpers for the ZCode rules.

The vocabulary lives in :mod:`skillsaw.formats.zcode`. What is here is the
rule-side machinery more than one rule needs: the repository types each
rule activates in, and the hook matcher-group check that plugin hooks and
project configuration share.
"""

from __future__ import annotations

from typing import Any, List

from skillsaw.context import RepositoryType
from skillsaw.diagnostics import safe_display
from skillsaw.formats.zcode import HOOK_TYPES
from skillsaw.utils import is_finite_number

# A ZCode marketplace repository contains the plugins it catalogs, so the
# plugin rules fire there too — the reason the Grok and Codex sets carry
# their marketplace type alongside the plugin type.
ZCODE_PLUGIN_REPO_TYPES = frozenset({RepositoryType.ZCODE_PLUGIN, RepositoryType.ZCODE_MARKETPLACE})
ZCODE_MARKETPLACE_REPO_TYPES = frozenset({RepositoryType.ZCODE_MARKETPLACE})
ZCODE_PROJECT_REPO_TYPES = frozenset({RepositoryType.ZCODE_PROJECT})


def is_positive_number(value: Any) -> bool:
    """A finite JSON number above zero; overflow-safe for huge integers."""
    return is_finite_number(value) and value > 0


def _is_positive_int(value: Any) -> bool:
    if isinstance(value, float) and value.is_integer():
        value = int(value)  # JSON ``5000.0`` is an integer to JavaScript
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def matcher_group_problems(group: Any, *, project: bool) -> List[str]:
    """Why ZCode refuses one ``{matcher?, hooks: [...]}`` group, or ``[]``.

    The plugin loader validates each group with ``HookMatcherConfigSchema``
    (``contracts/src/hooks/index.ts:393-424`` in ``zai-org/ZCode``) and
    drops a group that fails. Project configuration uses the config-file
    copy of that schema (``adapters/src/config/schema.ts:236-269``), which
    differs in three places selected by *project*: ``matcher`` and
    ``statusMessage`` must be non-empty, and ``timeoutMs`` is any positive
    number rather than a positive integer. Unknown handler keys are allowed
    by both.
    """
    if not isinstance(group, dict):
        return ["a matcher group must be an object"]
    problems: List[str] = []
    if project:
        # The config-file matcher group is a strict object
        # (``adapters/src/config/schema.ts:264-269``); the plugin one is not.
        unknown = sorted(set(group) - {"matcher", "hooks"})
        if unknown:
            problems.append(
                f"unknown key(s) {', '.join(repr(safe_display(k)) for k in unknown)}; "
                "a matcher group takes only 'matcher' and 'hooks'"
            )
    matcher = group.get("matcher")
    if "matcher" in group and (not isinstance(matcher, str) or (project and not matcher)):
        problems.append(
            "'matcher' must be a non-empty string" if project else "'matcher' must be a string"
        )
    handlers = group.get("hooks")
    if not isinstance(handlers, list) or not handlers:
        problems.append("'hooks' must be a non-empty array of handlers")
        return problems
    timeout_ms_ok = is_positive_number if project else _is_positive_int
    for index, handler in enumerate(handlers):
        where = f"hooks[{index}]"
        if not isinstance(handler, dict):
            problems.append(f"{where} must be an object")
            continue
        kind = handler.get("type")
        if kind not in HOOK_TYPES:
            problems.append(
                f"{where}.type must be one of {', '.join(HOOK_TYPES)} (got {safe_display(kind)!r}); "
                "ZCode has no prompt, agent, http or mcp_tool handlers"
            )
            continue
        command = handler.get("command")
        if not isinstance(command, str) or not command:
            problems.append(f"{where}.command must be a non-empty string")
        if "enabled" in handler and not isinstance(handler["enabled"], bool):
            problems.append(f"{where}.enabled must be a boolean")
        if "onError" in handler and handler["onError"] not in ("allow", "deny"):
            problems.append(f"{where}.onError must be 'allow' or 'deny'")
        if "statusMessage" in handler:
            message = handler["statusMessage"]
            if not isinstance(message, str) or (project and not message):
                problems.append(f"{where}.statusMessage must be a string")
        if "timeoutMs" in handler and not timeout_ms_ok(handler["timeoutMs"]):
            problems.append(
                f"{where}.timeoutMs must be a positive number"
                if project
                else f"{where}.timeoutMs must be a positive integer"
            )
        if kind == "process":
            args = handler.get("args")
            if "args" in handler and (
                not isinstance(args, list) or not all(isinstance(a, str) for a in args)
            ):
                problems.append(f"{where}.args must be an array of strings")
            continue
        if "async" in handler and not isinstance(handler["async"], bool):
            problems.append(f"{where}.async must be a boolean")
        if "shell" in handler:
            shell = handler["shell"]
            if shell is not True and not (isinstance(shell, str) and shell):
                problems.append(f"{where}.shell must be true or a non-empty string")
        if "timeout" in handler and not is_positive_number(handler["timeout"]):
            problems.append(f"{where}.timeout must be a positive number")
    return problems

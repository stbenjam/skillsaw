"""
Rule: hooks-dangerous

Flags hook commands that match dangerous patterns: executing scripts from
dotfile directories, download-and-execute, obfuscation, and suspicious
runtimes or network access.
"""

import re
from typing import Dict, List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.content_analysis import (
    HookEventConfig,
    HooksBlock,
    SettingsBlock,
)

_INTERPRETERS = r"(?:node|bun|deno|python[23]?|ruby|perl|php|bash|sh|zsh|dash)"
_INTERPRETER_CMD = rf"(?:(?:\S+/)?env\s+)?(?:\S+/)?{_INTERPRETERS}"
_SUDO = r"(?:sudo\s+)?"
_DOTFILE_DIRS = r"\.(?:claude|vscode|cursor|codex|github|windsurf)"

_SCRIPT_FROM_DOTFILES_RE = re.compile(
    rf"""(?:^|&&|\|\||;|\|)\s*
        {_SUDO}                              # optional sudo
        (?:{_INTERPRETER_CMD})\s+(?:run\s+)? # interpreter [run]
        (?:\S+/)?{_DOTFILE_DIRS}/\S+         # path under dotfile dir
    """,
    re.VERBOSE,
)

_DOWNLOAD_EXEC_RE = re.compile(
    rf"""
        (?:curl|wget)\b[^|;]*       # download tool with args
        \|\s*                        # piped to
        {_SUDO}                      # optional sudo
        (?:{_INTERPRETER_CMD})       # interpreter
    """,
    re.VERBOSE,
)

_DOWNLOAD_CHAIN_RE = re.compile(
    rf"""
        (?:curl|wget)\b.*            # download tool
        (?:&&|;)\s*                  # chained
        {_SUDO}                      # optional sudo
        (?:{_INTERPRETER_CMD})\s+\S+ # interpreter + file
    """,
    re.VERBOSE,
)

_OBFUSCATION_RE = re.compile(
    r"""
        \beval\s+["\$(\`]                      # eval with expansion
        |base64\s+(?:-d|--decode)              # base64 decode
        |\becho\b.*\|\s*base64\s+(?:-d|--decode)  # piping to base64 decode
    """,
    re.VERBOSE,
)

_BUN_RE = re.compile(rf"(?:^|&&|\|\||;|\|)\s*{_SUDO}(?:\S+/)?bun\s+(?:run\s+)?\S+")

_NETWORK_FETCH_RE = re.compile(rf"(?:^|&&|\|\||;|\|)\s*{_SUDO}(?:curl|wget|nc|ncat)\b")


def _check_dangerous(command: str) -> List[str]:
    """Return messages for dangerous patterns in a command."""
    findings: List[str] = []

    if _SCRIPT_FROM_DOTFILES_RE.search(command):
        findings.append("executes a script from a dotfile directory")

    if _DOWNLOAD_EXEC_RE.search(command) or _DOWNLOAD_CHAIN_RE.search(command):
        findings.append("downloads and executes remote code")

    if _OBFUSCATION_RE.search(command):
        findings.append("uses obfuscation techniques (eval/base64)")

    if not findings and _BUN_RE.search(command):
        findings.append("uses bun runtime (uncommon in hooks, verify intent)")

    if not findings and _NETWORK_FETCH_RE.search(command):
        findings.append("performs network requests (verify intent)")

    return findings


class HooksDangerousRule(Rule):
    """Flag hook commands matching dangerous patterns."""

    since = "0.12.0"

    config_schema = {
        "allowlist": {
            "type": "list",
            "default": [],
            "description": "Hook commands to permit (exact match)",
        },
    }

    @property
    def rule_id(self) -> str:
        return "hooks-dangerous"

    @property
    def description(self) -> str:
        return (
            "Flags hook commands that execute scripts from dotfile directories, "
            "download-and-execute chains (curl|sh), obfuscation (eval/base64), "
            "or perform network requests"
        )

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def _is_allowed(self, command: str) -> bool:
        allowlist = self.config.get("allowlist", [])
        return any(command == entry for entry in allowlist)

    def _check_events(
        self,
        events: Dict[str, List[HookEventConfig]],
        file_path,
    ) -> List[RuleViolation]:
        violations = []
        for event_type, configs in events.items():
            for cfg in configs:
                for handler in cfg.handlers:
                    if handler.type != "command" or not handler.command:
                        continue
                    # Exec-form hooks split the invocation across command +
                    # args; scan the joined form so patterns can't hide in args.
                    command = handler.command
                    if isinstance(handler.args, list):
                        command = " ".join([command, *(str(a) for a in handler.args)])
                    if self._is_allowed(handler.command) or self._is_allowed(command):
                        continue
                    for message in _check_dangerous(command):
                        violations.append(
                            self.violation(
                                f"Hook {event_type}: {message} — " f"command: {command!r}",
                                file_path=file_path,
                            )
                        )
        return violations

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        for block in context.lint_tree.find(HooksBlock):
            if block.parse_error:
                continue
            violations.extend(self._check_events(block.events, block.path))

        for block in context.lint_tree.find(SettingsBlock):
            if block.parse_error:
                continue
            violations.extend(self._check_events(block.hooks_events, block.path))

        return violations

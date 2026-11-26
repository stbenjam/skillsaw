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

import errno
import json
import os
import re
import shlex
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple
from urllib.parse import parse_qsl, unquote, urlsplit, urlunsplit

import yaml

from .diagnostics import encodable, safe_display
from .formats import mcp_skills
from .formats.mcp_skills import DEFAULT_MAX_BYTES, DEFAULT_MAX_SKILLS, DEFAULT_TIMEOUT
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
from .paths import safe_resolve
from .utils import (
    _SAFE_LOADER,
    mkdir_parents_anchored,
    parse_frontmatter,
    read_jsonc,
    remove_contained_files_and_empty_dirs,
    write_bytes_atomic,
    write_bytes_exclusive,
)

#: Bounds on discovering a dynamic skill's files through directory reads.
MAX_DIRECTORY_DEPTH = 8
MAX_DIRECTORY_REQUESTS = 128

_ENV_REF = re.compile(r"\$\{(?:env:)?([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
_UNSUPPORTED_PLACEHOLDER = re.compile(r"\$\{input:[^}]*\}")


class PullError(Exception):
    """A target or output directory the pull cannot use."""


class SkipServerError(PullError):
    """A configured server that is intentionally skipped rather than malformed."""


@dataclass
class ServerTarget:
    """How to reach one server, and the directory its skills land in."""

    label: str
    kind: str  # "http" or "stdio"
    url: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    command: List[str] = field(default_factory=list)
    env: Optional[Dict[str, str]] = None
    configured_env: Dict[str, str] = field(default_factory=dict)
    configured_secrets: Tuple[str, ...] = ()
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


def _expand(value: str, *, secrets_out: Optional[set] = None) -> str:
    """Expand ``${VAR}``, ``${VAR:-default}``, and VS Code ``${env:VAR}`` placeholders."""
    if _UNSUPPORTED_PLACEHOLDER.search(value):
        raise PullError(
            "uses an interactive ${input:...} placeholder that skillsaw cannot prompt for"
        )

    def substitute(match: "re.Match[str]") -> str:
        name, default = match.group(1), match.group(2)
        if name in os.environ:
            expanded = os.environ[name]
            if secrets_out is not None:
                upper = name.upper()
                min_len = 4 if any(tok in upper for tok in _ENV_SECRET_KEY_TOKENS) else 8
                _add_token_variants(secrets_out, expanded, min_len=min_len)
            return expanded
        return default if default is not None else match.group(0)

    return _ENV_REF.sub(substitute, value)


def parse_header(spec: str) -> tuple:
    """``Name: value`` from the command line."""
    name, sep, value = spec.partition(":")
    if not sep or not name.strip():
        # Never quote the argument: it is usually a credential.
        raise PullError("a --mcp-header must look like 'Name: value'")
    return name.strip(), value.strip()


_HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")


_PATH_SECRET_PREFIXES = (
    "sk-",
    "sk_",
    "ghp_",
    "gho_",
    "ghu_",
    "ghs_",
    "ghr_",
    "glpat-",
    "pat_",
    "tok_",
    "key_",
    "api_",
    "xox",
)


def _path_secret_segments(path: str) -> List[str]:
    """URL path segments that look like embedded API keys or tokens."""
    found: List[str] = []
    for raw in path.split("/"):
        if not raw:
            continue
        decoded = unquote(raw)
        lowered = decoded.lower()
        is_secret = (len(decoded) >= 8 and lowered.startswith(_PATH_SECRET_PREFIXES)) or (
            len(decoded) >= 12
            and any(ch.isdigit() for ch in decoded)
            and any(ch.isalpha() for ch in decoded)
        )
        if is_secret:
            found.append(raw)
            if decoded != raw:
                found.append(decoded)
    return found


def url_target(
    url: str,
    headers: Mapping[str, str],
    label: Optional[str] = None,
    *,
    configured_secrets: Tuple[str, ...] = (),
) -> ServerTarget:
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
    if parts.scheme == "http" and not mcp_skills.is_loopback_host(host):
        if headers or parts.query or _path_secret_segments(parts.path) or configured_secrets:
            raise PullError(
                "refusing to send HTTP headers or URL credentials over unencrypted http://; "
                "use https:// (cleartext http:// with credentials is allowed only for loopback hosts)"
            )
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
        configured_secrets=configured_secrets,
    )


#: Commands that start the server their first plain argument names, and the
#: verbs some of them take first (``uv run``, ``docker run``, ``pnpm dlx``).
_LAUNCHERS = {"npx", "pnpx", "bunx", "uvx", "pipx", "uv", "pnpm", "node", "deno", "bun", "docker"}
_LAUNCHER_VERBS = {"run", "x", "exec", "dlx", "tool"}
#: Flags whose presence still leaves the next plain token as a safe package/module name.
#: Any other flag before the target may take a value carrying a credential (e.g.
#: ``docker run --env KEY=secret`` or ``uvx --index-url https://u:p@host``) or inline code.
_SAFE_LABEL_FLAGS = {"-y", "--yes", "-q", "--quiet", "--rm", "-i", "--interactive", "-m"}


def _command_label(command: List[str]) -> str:
    """Name a stdio server for its snapshot directory, from its command line.

    ``npx -y @acme/skills-server`` is "skills-server" and ``python -m
    acme.server`` is "acme.server"; any other program — or a launcher carrying
    unknown flags whose values may hold credentials — is named for itself.
    """
    program = Path(command[0])
    launcher = program.stem.lower()
    if launcher in _LAUNCHERS or launcher.startswith("python"):
        for arg in command[1:]:
            if arg in _LAUNCHER_VERBS or arg in _SAFE_LABEL_FLAGS:
                continue
            if arg.startswith("-"):
                return program.name
            if "=" in arg or (":" in arg and "@" in arg):
                return program.name
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
    servers = None
    for key in ("mcpServers", "servers"):
        candidate = data.get(key)
        if not isinstance(candidate, Mapping) or _looks_like_server(candidate):
            continue
        # In a bare map, an entry named "servers"/"mcpServers" with only
        # ``{"disabled": true}`` beside real server siblings is itself a
        # disabled server entry, not a wrapper map.
        if (
            candidate.get("disabled") is True
            and not any(_looks_like_server(v) for v in candidate.values())
            and any(_looks_like_server(v) for k, v in data.items() if k != key)
        ):
            continue
        servers = candidate
        break
    has_invalid_wrapper = any(
        k in data and not isinstance(data[k], Mapping) for k in ("mcpServers", "servers")
    )
    has_sibling_server = any(
        _looks_like_server(v) for k, v in data.items() if k not in ("mcpServers", "servers")
    )
    if (
        servers is None
        and data
        and (not has_invalid_wrapper or has_sibling_server)
        and any(
            _looks_like_server(entry)
            or (isinstance(entry, Mapping) and entry.get("disabled") is True)
            for entry in data.values()
        )
    ):
        servers = data
    if not isinstance(servers, Mapping):
        raise PullError(f"{config_path} has no 'mcpServers' or 'servers' map")
    return {str(k): v for k, v in servers.items()}


def _looks_like_server(entry: Any) -> bool:
    """Whether *entry* carries string launch fields (distinguishing it from a wrapper map)."""
    if not isinstance(entry, Mapping):
        return False
    return isinstance(entry.get("command"), str) or isinstance(entry.get("url"), str)


_HTTP_TYPES = frozenset({"http", "streamable-http", "streamable_http", "streamablehttp"})


def config_target(name: str, entry: Any, cwd: Path) -> ServerTarget:
    """A target for one server entry of an MCP client config."""
    if not isinstance(entry, Mapping):
        raise PullError("it is not an object")
    if entry.get("disabled") is True:
        raise SkipServerError("it is disabled")  # never start a server the user switched off
    label = mcp_skills.sanitize_label(name)
    if "type" in entry:
        raw_kind = entry["type"]
        if not isinstance(raw_kind, str):
            raise PullError("its 'type' is not a string")
        kind = raw_kind.strip().lower()
        if kind == "sse":
            raise SkipServerError("it uses the retired HTTP+SSE transport")
        if kind in _HTTP_TYPES:
            transport = "http"
        elif kind == "stdio":
            transport = "stdio"
        else:
            raise PullError("its 'type' is not supported")
    elif "url" in entry and "command" not in entry:
        transport = "http"
    elif "command" in entry:
        transport = "stdio"
    else:
        raise PullError("it has neither a 'url' nor a 'command'")

    if transport == "http":
        url = entry.get("url")
        if not isinstance(url, str) or not url:
            raise PullError("its 'url' is missing or not a string")
        raw_headers = entry.get("headers") if "headers" in entry else {}
        if not isinstance(raw_headers, Mapping):
            raise PullError("its 'headers' is not an object")
        if not all(isinstance(v, str) for v in raw_headers.values()):
            raise PullError("its 'headers' holds a value that is not a string")
        expanded_secrets: set = set()
        expanded = {
            str(k): _expand(v, secrets_out=expanded_secrets) for k, v in raw_headers.items()
        }
        target = url_target(
            _expand(url, secrets_out=expanded_secrets),
            expanded,
            configured_secrets=tuple(sorted(expanded_secrets, key=len, reverse=True)),
        )
        target.label = label
        return target

    command = entry.get("command")
    if not isinstance(command, str) or not command:
        raise PullError("its 'command' is missing or not a string")
    args = entry["args"] if "args" in entry else []
    if not isinstance(args, list):
        # Dropping them would start a different program invocation.
        raise PullError("its 'args' is not an array")
    if not all(isinstance(arg, str) for arg in args):
        raise PullError("its 'args' holds a value that is not a string")
    expanded_secrets = set()
    argv = [_expand(command, secrets_out=expanded_secrets)] + [
        _expand(a, secrets_out=expanded_secrets) for a in args
    ]
    env = dict(os.environ)
    configured_env: Dict[str, str] = {}
    if "env" in entry:
        raw_env = entry["env"]
        if not isinstance(raw_env, Mapping):
            raise PullError("its 'env' is not an object")  # as with args, never drop it
        if not all(isinstance(v, str) for v in raw_env.values()):
            raise PullError("its 'env' holds a value that is not a string")
        configured_env = {
            str(k): _expand(v, secrets_out=expanded_secrets) for k, v in raw_env.items()
        }
        env.update(configured_env)
    if "cwd" in entry:
        workdir = entry["cwd"]
        if not isinstance(workdir, str):
            raise PullError("its 'cwd' is not a string")  # never start it elsewhere
        if workdir:
            cwd = cwd / _expand(workdir)  # relative to the config, as clients resolve it
    return ServerTarget(
        label=label,
        kind="stdio",
        command=argv,
        env=env,
        configured_env=configured_env,
        configured_secrets=tuple(sorted(expanded_secrets, key=len, reverse=True)),
        cwd=cwd,
    )


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
    """Create *out_dir*, replacing an earlier skillsaw snapshot but nothing else.

    Existing content is removed only when every file in *out_dir* is either
    ``mcp-skills-snapshot.json`` (carrying a valid skillsaw header) or a
    regular non-symlink file inside a server directory listed in that
    snapshot's ``files`` inventory. Only inventoried files are unlinked and
    only emptied directories are pruned with ``rmdir`` — arbitrary trees are
    never recursively deleted.
    """
    try:
        if out_dir.exists() or out_dir.is_symlink():
            if not out_dir.is_dir() or out_dir.is_symlink():
                raise PullError(f"{out_dir} exists and is not a directory")
            entries = list(out_dir.iterdir())
            if entries:
                files_to_unlink, dirs_to_rmdir, record_file = _verify_replaceable_snapshot(
                    out_dir, entries
                )
                # Unlink inventoried files, prune now-empty dirs, remove the
                # snapshot record last so an interrupted cleanup stays valid.
                for path in files_to_unlink:
                    path.unlink()
                for directory in dirs_to_rmdir:
                    directory.rmdir()
                if record_file is not None:
                    record_file.unlink()
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise PullError(f"cannot prepare {out_dir}: {exc.strerror or exc}") from exc


def _safe_inventory_parts(rel: Any) -> Optional[Tuple[str, ...]]:
    """Relative path parts from a snapshot ``files`` entry, or ``None`` if unsafe."""
    if not isinstance(rel, str) or not rel or rel.startswith("/") or "\\" in rel or "\x00" in rel:
        return None
    parts = tuple(rel.split("/"))
    if any(part in ("", ".", "..") for part in parts):
        return None
    return parts


def _snapshot_inventory(out_dir: Path) -> Optional[Dict[str, set]]:
    """Map each recorded server label to its set of inventoried file-part tuples."""
    data = mcp_skills.read_snapshot_record(out_dir)
    if not isinstance(data, dict):
        return None
    if data.get("snapshotVersion") != mcp_skills.SNAPSHOT_VERSION:
        return None
    generator = data.get("generator")
    if not isinstance(generator, str) or not generator.startswith("skillsaw "):
        return None
    servers = data.get("servers")
    if not isinstance(servers, list):
        return None
    inventory: Dict[str, set] = {}
    for server in servers:
        if not isinstance(server, dict):
            return None
        label = server.get("label")
        raw_files = server.get("files")
        if (
            not isinstance(label, str)
            or mcp_skills.sanitize_label(label) != label
            or not isinstance(raw_files, list)
        ):
            return None
        file_set = inventory.setdefault(label, set())
        for rel in raw_files:
            parts = _safe_inventory_parts(rel)
            if parts is None:
                return None
            file_set.add(parts)
    return inventory


def _verify_replaceable_snapshot(
    out_dir: Path, entries: List[Path]
) -> Tuple[List[Path], List[Path], Optional[Path]]:
    """Verify every item in *out_dir* belongs to its snapshot inventory."""
    not_snapshot = (
        f"{out_dir} holds files that are not a skillsaw snapshot; choose an "
        "empty directory or an earlier snapshot"
    )
    inventory = _snapshot_inventory(out_dir)
    if inventory is None:
        raise PullError(not_snapshot)

    record_file: Optional[Path] = None
    files_to_unlink: List[Path] = []
    dirs_to_rmdir: List[Path] = []

    for entry in entries:
        if entry.is_symlink():
            raise PullError(not_snapshot)
        if entry.name == mcp_skills.SNAPSHOT_FILENAME:
            if not entry.is_file():
                raise PullError(not_snapshot)
            record_file = entry
            continue
        if (
            entry.name not in inventory
            or mcp_skills.sanitize_label(entry.name) != entry.name
            or not entry.is_dir()
        ):
            raise PullError(not_snapshot)
        expected = inventory[entry.name]
        server_dirs: List[Path] = []
        for dirpath, dirnames, filenames in os.walk(entry, topdown=True, followlinks=False):
            current = Path(dirpath)
            server_dirs.append(current)
            for name in dirnames:
                if (current / name).is_symlink():
                    raise PullError(not_snapshot)
            for name in filenames:
                file_path = current / name
                if file_path.is_symlink() or not file_path.is_file():
                    raise PullError(not_snapshot)
                rel_parts = file_path.relative_to(entry).parts
                if rel_parts not in expected:
                    raise PullError(not_snapshot)
                files_to_unlink.append(file_path)
        # Bottom-up order so deepest subdirectories are rmdir'd first.
        dirs_to_rmdir.extend(reversed(server_dirs))

    if record_file is None:
        raise PullError(not_snapshot)
    return files_to_unlink, dirs_to_rmdir, record_file


def _write_exclusive(path: Path, data: bytes, root: Path) -> None:
    """Create *path* exclusively inside *root*, anchored against symlink swaps."""
    try:
        write_bytes_exclusive(path, data, root=root)
    except FileExistsError:
        raise
    except OSError as exc:
        if (
            exc.errno in (errno.ELOOP, errno.ENOTDIR)
            or "escapes root" in str(exc)
            or "symlink" in str(exc)
        ):
            raise PullError(f"refused to write outside the snapshot: {path}") from exc
        raise


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


_ENV_SECRET_KEY_TOKENS = (
    "TOKEN",
    "SECRET",
    "KEY",
    "PASS",
    "AUTH",
    "CRED",
    "COOKIE",
    "SESSION",
    "BEARER",
    "PAT",
    "PWD",
    "PRIVATE",
)


def _add_token_variants(values: set, raw: str, *, min_len: int) -> None:
    stripped = raw.strip()
    if len(stripped) >= min_len:
        values.add(stripped)
        parts = stripped.split()
        if len(parts) >= 2 and len(parts[-1]) >= min_len:
            values.add(parts[-1])


_SECRET_SHORT_FLAGS = frozenset({"-H", "-k", "-p", "-t", "-e"})


def _is_secret_flag(flag: str) -> bool:
    if flag in _SECRET_SHORT_FLAGS:
        return True
    if flag.startswith("-"):
        upper = flag.lstrip("-").upper()
        return any(tok in upper for tok in _ENV_SECRET_KEY_TOKENS) or upper == "HEADER"
    return False


def _secret_values(target: ServerTarget) -> Tuple[str, ...]:
    """Sensitive strings sent to *target* that must not echo into snapshots or logs."""
    values: set = set(target.configured_secrets)
    for raw in target.headers.values():
        _add_token_variants(values, raw, min_len=4)
    for key, raw in target.configured_env.items():
        upper = key.upper()
        min_len = 4 if any(tok in upper for tok in _ENV_SECRET_KEY_TOKENS) else 8
        _add_token_variants(values, raw, min_len=min_len)
    if target.url:
        parts = urlsplit(target.url)
        for seg in _path_secret_segments(parts.path):
            values.add(seg)
        query = parts.query
        if len(query) >= 6:
            values.add(query)
        for segment in query.split("&"):
            _k, sep, raw_val = segment.partition("=")
            if sep and len(raw_val) >= 6:
                values.add(raw_val)
        for _key, val in parse_qsl(query, keep_blank_values=False):
            if len(val) >= 6:
                values.add(val)
    prev_secret_flag = False
    for arg in target.command[1:]:
        if "=" in arg:
            lhs, _, rhs = arg.partition("=")
            upper = lhs.lstrip("-").upper()
            min_len = 4 if any(tok in upper for tok in _ENV_SECRET_KEY_TOKENS) else 8
            _add_token_variants(values, rhs, min_len=min_len)
            prev_secret_flag = False
        elif prev_secret_flag:
            _add_token_variants(values, arg, min_len=4)
            prev_secret_flag = False
        else:
            prev_secret_flag = _is_secret_flag(arg)
    return tuple(sorted(values, key=len, reverse=True))


def _redact_secrets(text: str, secrets: Tuple[str, ...]) -> str:
    for secret in secrets:
        if secret in text:
            text = text.replace(secret, "[redacted]")
    return text


def _redact_value(value: Any, secrets: Tuple[str, ...], *, skip_keys: Tuple[str, ...] = ()) -> Any:
    """Scrub *secrets* from strings inside a JSON-compatible *value*."""
    if not secrets:
        return value
    if isinstance(value, str):
        return _redact_secrets(value, secrets)
    if isinstance(value, list):
        return [_redact_value(item, secrets, skip_keys=skip_keys) for item in value]
    if isinstance(value, Mapping):
        return {
            (k if k in skip_keys else _redact_secrets(k, secrets) if isinstance(k, str) else k): (
                v if k in skip_keys else _redact_value(v, secrets, skip_keys=skip_keys)
            )
            for k, v in value.items()
        }
    return value


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
        if served is not None and isinstance(advertised, str):
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
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None
    parsed, _, _ = parse_frontmatter(text)
    return parsed


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
                f"frontmatter name {safe_display(frontmatter.get('name'))!r} does not equal "
                f"the URI's final segment {name!r}"
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


_OVER_SKILL_LIMIT = object()


class _ServerPull:
    """Fetch one server's skills into ``<out_dir>/<label>``."""

    def __init__(self, target: ServerTarget, out_dir: Path, *, max_skills: int, max_bytes: int):
        self.target = target
        self.out_dir = safe_resolve(out_dir) or out_dir
        self.server_dir = self.out_dir / target.label
        self.max_skills = max_skills
        self.max_bytes = max_bytes
        self._secrets = _secret_values(target)
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
            "target": encodable(target.describe()),
            "protocolVersion": None,
            "serverInfo": None,
            "extension": None,
            "files": [],
            "skills": [],
            "errors": [],
        }

    def error(self, message: str, uri: Optional[str] = None) -> None:
        entry: Dict[str, Any] = {"message": encodable(_redact_secrets(message, self._secrets))}
        if uri is not None:
            entry["uri"] = encodable(_redact_secrets(uri, self._secrets))
        self.record["errors"].append(entry)

    def run(self, timeout: float) -> Dict[str, Any]:
        try:
            transport = self.target.open()
        except McpError as exc:
            self.error(f"could not connect: {exc}")
            return self.record
        # Every response — listing pages, directory reads, files — counts
        # against one byte budget and one aggregate duration ceiling, so no
        # server can make a pull read or trickle without end.
        session = McpSession(
            transport,
            timeout=timeout,
            max_bytes=self.max_bytes,
            max_duration=timeout * 20 if timeout > 0 else None,
        )
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
        self.record["protocolVersion"] = encodable(
            _redact_secrets(str(info.protocol_version), self._secrets)
        )
        if info.server_info:
            self.record["serverInfo"] = {
                key: encodable(_redact_secrets(info.server_info[key], self._secrets))
                for key in ("name", "version")
                if isinstance(info.server_info.get(key), str)
            }
        for cap_error in info.skills_extension_errors():
            self.error(cap_error)
        extension = info.skills_extension
        if extension is None:
            self.record["extension"] = None
            return  # serving no skills (or a non-object declaration already recorded above)
        recorded_ext = _jsonable(extension)
        if recorded_ext is None:
            self.error(
                "skills extension settings cannot be recorded: they nest too deeply, or "
                "hold a non-finite number or text that is not valid Unicode"
            )
            self.record["extension"] = {}
        else:
            self.record["extension"] = _redact_value(recorded_ext, self._secrets)
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
            # Keep raw URI keys so snapshot_skill_dirs() can resolve written skills;
            # scrub reflected secrets from all other recorded metadata fields.
            self.record["skills"].append(_redact_value(recorded, self._secrets, skip_keys=("uri",)))
            entries.append(entry)
        mkdir_parents_anchored(self.server_dir, root=self.out_dir)
        for entry in entries:
            self._pull_skill(session, entry, extension)

    def _pull_skill(
        self, session: McpSession, entry: Mapping[str, Any], extension: Mapping[str, Any]
    ) -> None:
        uri = entry.get("uri")
        root_uri = mcp_skills.skill_root_uri(uri) if isinstance(uri, str) else None
        if root_uri is None or mcp_skills.local_parts(uri) is None:
            self.error(
                f"skills/list entry uri {safe_display(uri)!r} does not name a skill's SKILL.md",
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
            remaining = mcp_skills.MAX_BYTES_PER_SKILL - skill_bytes
            # A file another listed skill already fetched still counts here.
            if file_uri in self.fetched:
                if self.fetched[file_uri][0] > remaining:
                    self.error("stopped: the skill's files exceed 16 MiB", file_uri)
                    return
                skill_bytes += self.fetched[file_uri][0]
            else:
                result = self._fetch(session, file_uri, max_bytes=remaining)
                if result is _OVER_SKILL_LIMIT:
                    return
                if result is None:
                    continue
                assert isinstance(result, bytes)
                skill_bytes += len(result)
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

    def _fetch(self, session: McpSession, file_uri: str, *, max_bytes: Optional[int] = None) -> Any:
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
                f"refused: on macOS or Windows its path is the same as {self.stored[folded]}",
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
        if max_bytes is not None and len(data) > max_bytes:
            self.stored.pop(folded, None)
            self.error("stopped: the skill's files exceed 16 MiB", file_uri)
            return _OVER_SKILL_LIMIT
        self.fetched[file_uri] = (len(data), mcp_skills.sha256_digest(data))
        if parts[-1] == mcp_skills.SKILL_FILENAME:
            self.frontmatter[file_uri] = _served_frontmatter(data)
        rel_path = "/".join(parts)
        self.record["files"].append(rel_path)
        try:
            _write_exclusive(self.server_dir.joinpath(*parts), data, self.out_dir)
        except PullError as exc:
            self.record["files"].pop()
            self.error(f"refused: {exc}", file_uri)
        except FileExistsError:
            self.record["files"].pop()
            self.error("refused: another resource already maps to this file", file_uri)
        except OSError as exc:
            if not getattr(exc, "_skillsaw_partial_file_retained", False):
                self.record["files"].pop()
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
            outside = 0
            for child in children:
                child_uri = child.get("uri")
                if not isinstance(child_uri, str):
                    unnamed += 1  # it may be a file this walk would then leave out
                    continue
                parent, _, name = child_uri.rpartition("/")
                if parent != directory or not name:
                    outside += 1  # not a direct child of the directory read
                    continue
                if child.get("mimeType") == "inode/directory":
                    if mcp_skills.local_parts(child_uri) is None:
                        self.error("refused: the URI cannot be stored safely", child_uri)
                        continue
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
            if outside:
                self.error(
                    f"{outside} directory listing entr{'y' if outside == 1 else 'ies'} are not "
                    "direct children of the directory; the skill's file list may be incomplete",
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
    timeout: float = DEFAULT_TIMEOUT,
    max_skills: int = DEFAULT_MAX_SKILLS,
    max_bytes: int = DEFAULT_MAX_BYTES,
    progress: Optional[Callable[[ServerTarget], None]] = None,
    config_errors: Optional[List[Tuple[str, str]]] = None,
) -> Dict[str, Any]:
    """Fetch every target's skills into *out_dir* and write the snapshot."""
    from . import __version__

    unique_labels(targets)
    started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    unfinished = {"message": "the pull did not finish"}
    error_records = [
        {
            "label": mcp_skills.sanitize_label(name),
            "transport": None,
            "target": None,
            "protocolVersion": None,
            "serverInfo": None,
            "extension": None,
            "files": [],
            "skills": [],
            "errors": [{"message": encodable(message)}],
        }
        for name, message in (config_errors or ())
    ]
    # Recorded before anything is fetched: a pull cut short still leaves a
    # record of the directories it made, so the next pull can replace them.
    _write_snapshot(
        out_dir,
        {
            "snapshotVersion": mcp_skills.SNAPSHOT_VERSION,
            "generator": f"skillsaw {__version__}",
            "pulledAt": started,
            "servers": [{"label": t.label, "files": [], "errors": [unfinished]} for t in targets]
            + error_records,
        },
    )
    pulls = [
        _ServerPull(target, out_dir, max_skills=max_skills, max_bytes=max_bytes)
        for target in targets
    ]
    servers: List[Dict[str, Any]] = []
    try:
        for runner in pulls:
            if progress is not None:
                progress(runner.target)
            servers.append(runner.run(timeout))
    except BaseException:
        # Preserve the exact files already written before re-raising so a
        # subsequent pull can cleanly replace this interrupted snapshot.
        partial_servers = list(servers)
        for runner in pulls[len(servers) :]:
            partial_servers.append(
                {
                    **runner.record,
                    "errors": list(runner.record["errors"]) + [unfinished],
                }
            )
        partial_servers.extend(error_records)
        _persist_or_rollback_snapshot(
            out_dir,
            {
                "snapshotVersion": mcp_skills.SNAPSHOT_VERSION,
                "generator": f"skillsaw {__version__}",
                "pulledAt": started,
                "servers": partial_servers,
            },
            started=started,
            generator=f"skillsaw {__version__}",
            unfinished=unfinished,
        )
        raise
    servers.extend(error_records)
    snapshot = {
        "snapshotVersion": mcp_skills.SNAPSHOT_VERSION,
        "generator": f"skillsaw {__version__}",
        "pulledAt": started,
        "servers": servers,
    }
    try:
        _write_snapshot(out_dir, snapshot)
    except PullError:
        _persist_or_rollback_snapshot(
            out_dir,
            None,
            started=started,
            generator=f"skillsaw {__version__}",
            unfinished=unfinished,
            servers=servers,
        )
        raise
    return snapshot


def _persist_or_rollback_snapshot(
    out_dir: Path,
    full_snapshot: Optional[Dict[str, Any]],
    *,
    started: str,
    generator: str,
    unfinished: Dict[str, str],
    servers: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """Keep *out_dir* replaceable after a failed write or interrupt.

    Tries *full_snapshot* when given, falls back to a minimal inventory-only
    snapshot, and if even that cannot be written removes the files this pull
    created so the provisional snapshot remains consistent with disk.
    """
    server_list = servers if servers is not None else (full_snapshot or {}).get("servers", [])
    if full_snapshot is not None:
        try:
            _write_snapshot(out_dir, full_snapshot)
            return
        except PullError:
            pass
    minimal = {
        "snapshotVersion": mcp_skills.SNAPSHOT_VERSION,
        "generator": generator,
        "pulledAt": started,
        "servers": [
            {
                "label": s["label"],
                "files": list(s.get("files") or []),
                "errors": [unfinished],
            }
            for s in server_list
            if isinstance(s, Mapping) and isinstance(s.get("label"), str)
        ],
    }
    try:
        _write_snapshot(out_dir, minimal)
        return
    except PullError:
        pass
    tracked_files: List[Tuple[str, ...]] = []
    server_dirs: List[Tuple[str, ...]] = []
    for server in server_list:
        label = server.get("label") if isinstance(server, Mapping) else None
        if not isinstance(label, str) or mcp_skills.sanitize_label(label) != label:
            continue
        server_dirs.append((label,))
        for rel in server.get("files") or ():
            parts = _safe_inventory_parts(rel)
            if parts is not None:
                tracked_files.append((label, *parts))
    remove_contained_files_and_empty_dirs(out_dir, tracked_files, server_dirs)


def _write_snapshot(out_dir: Path, snapshot: Dict[str, Any]) -> None:
    """Atomically write the snapshot record as UTF-8 LF bytes within the reader's cap."""
    resolved_out = safe_resolve(out_dir) or out_dir
    final = resolved_out / mcp_skills.SNAPSHOT_FILENAME
    payload = (json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    if len(payload) > mcp_skills.MAX_SNAPSHOT_RECORD_BYTES:
        payload = (json.dumps(snapshot, separators=(",", ":"), ensure_ascii=False) + "\n").encode(
            "utf-8"
        )
    if len(payload) > mcp_skills.MAX_SNAPSHOT_RECORD_BYTES:
        raise PullError(
            f"snapshot record exceeds the {mcp_skills.MAX_SNAPSHOT_RECORD_BYTES}-byte limit"
        )
    if mcp_skills.exceeds_json_containers(payload, mcp_skills.MAX_SNAPSHOT_CONTAINERS):
        raise PullError(
            f"snapshot record exceeds the {mcp_skills.MAX_SNAPSHOT_CONTAINERS}-container limit"
        )
    try:
        write_bytes_atomic(final, payload, root=resolved_out)
    except OSError as exc:
        raise PullError(
            f"cannot write {out_dir / mcp_skills.SNAPSHOT_FILENAME}: {exc.strerror or exc}"
        ) from exc

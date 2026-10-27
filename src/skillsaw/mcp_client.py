"""A minimal MCP client: just enough protocol to fetch served skills.

``skillsaw lint --mcp-server`` needs ``skills/list``, ``resources/read`` and, for
dynamic skills, ``resources/directory/read`` — nothing else. The client speaks
both protocol eras over both standard transports, using the standard library
only:

* modern (``2026-07-28``): per-request ``_meta`` after a ``server/discover``
  probe, with the ``MCP-Protocol-Version``/``Mcp-Method``/``Mcp-Name`` headers
  on Streamable HTTP;
* legacy (``2025-11-25`` and earlier): the ``initialize`` handshake, with the
  ``Mcp-Session-Id`` header on Streamable HTTP.

The probe and fallback follow the spec's backward-compatibility rules: a
recognised modern error (``-32020``..``-32022``) means the server is modern;
anything else falls back to ``initialize``.

Everything a server sends is bounded: each request has one deadline, however
many notifications arrive first; each response is read in bounded pieces; and
a session can carry a byte budget that every response counts against.
"""

from __future__ import annotations

import base64
import functools
import http.client
import itertools
import json
import os
import queue
import re
import signal
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Tuple

from .formats.mcp_skills import EXTENSION_ID

MODERN_VERSION = "2026-07-28"
LEGACY_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
#: Modern-era JSON-RPC errors; seeing one means the server is not legacy.
MODERN_ERROR_CODES = frozenset({-32020, -32021, -32022})
UNSUPPORTED_VERSION = -32022
CLIENT_CAPABILITIES: Dict[str, Any] = {"extensions": {EXTENSION_ID: {}}}
#: Cap on one HTTP response or stdio line, far above the 16 MiB skill limit.
MAX_MESSAGE_BYTES = 64 * 1024 * 1024
#: Bytes taken from an HTTP body per read, so the deadline is checked often.
_READ_CHUNK = 64 * 1024
#: Messages a stdio server can get ahead of the client before its writes block.
_STDIO_BACKLOG = 64
#: Seconds a stdio server gets to exit at each step of shutdown.
_EXIT_GRACE = 2.0
#: Stands in for a stdio line that was not JSON, so its bytes are still counted.
_NOISE = object()
#: Retries of a request a busy server (HTTP 429 or 503) turned away, each
#: after its ``Retry-After`` or a doubling delay, all within the deadline.
_BUSY_RETRIES = 3


class McpError(Exception):
    """The server could not be reached or broke the protocol."""


class McpSizeError(McpError):
    """A response was larger than the caller allowed."""


class McpBudgetError(McpError):
    """The session's byte budget is spent."""


class McpAuthError(McpError):
    """The server wants credentials the request did not carry (HTTP 401)."""


class McpTimeoutError(McpError):
    """A request outlived its deadline: the server stopped answering."""


class McpRpcError(McpError):
    """The server answered a request with a JSON-RPC error."""

    def __init__(self, code: Any, message: Any, data: Any = None):
        super().__init__(f"{message} (code {code})")
        # Only an integer is a code; anything else (a list, say) cannot even
        # be looked up in a set of codes.
        self.code = code if isinstance(code, int) and not isinstance(code, bool) else None
        self.rpc_message = message
        self.data = data


def _client_info() -> Dict[str, str]:
    from . import __version__

    return {"name": "skillsaw", "version": __version__}


def _header_value(value: str) -> str:
    """Encode a header value with the spec's Base64 sentinel when needed."""
    plain = (
        value
        and value == value.strip()
        and all(0x20 <= ord(ch) <= 0x7E for ch in value)
        and not (value.startswith("=?base64?") and value.endswith("?="))
    )
    if plain:
        return value
    return "=?base64?" + base64.b64encode(value.encode("utf-8")).decode("ascii") + "?="


def _loads(data: Any) -> Any:
    """``json.loads``, treating nesting too deep for the parser as a server error."""
    try:
        return json.loads(data)
    except RecursionError:
        raise McpError("the server sent JSON nested too deeply to parse") from None


def _response_for(message: Any, request_id: int) -> Optional[Mapping[str, Any]]:
    """*message* if it is the response to *request_id*."""
    if isinstance(message, Mapping) and message.get("id") == request_id:
        if "result" in message or "error" in message:
            return message
    return None


def _timed_out(timeout: float, method: str) -> McpError:
    return McpTimeoutError(f"timed out after {timeout:g}s waiting for {method}")


def _check_deadline(deadline: float, timeout: float, method: str) -> None:
    if time.monotonic() >= deadline:
        raise _timed_out(timeout, method)


def _chunk_reader(stream) -> Callable[[int], bytes]:
    """A read that returns what has arrived rather than waiting for *n* bytes."""
    return getattr(stream, "read1", None) or stream.read


def _read_body(stream, *, deadline: float, timeout: float, method: str, limit: int) -> bytes:
    """A whole response body, read in bounded pieces within *limit* bytes."""
    read = _chunk_reader(stream)
    chunks: List[bytes] = []
    total = 0
    while True:
        _check_deadline(deadline, timeout, method)
        chunk = read(min(_READ_CHUNK, limit + 1 - total))
        if not chunk:
            return b"".join(chunks)
        total += len(chunk)
        if total > limit:
            raise McpSizeError(f"the response to {method} exceeded {limit} bytes")
        chunks.append(chunk)


def _unwrap(response: Mapping[str, Any]) -> Dict[str, Any]:
    if "error" in response:
        error = response.get("error")
        if not isinstance(error, Mapping):
            raise McpRpcError(None, "malformed error response")
        raise McpRpcError(error.get("code"), error.get("message"), error.get("data"))
    result = response.get("result")
    if not isinstance(result, dict):
        raise McpError("response result is not an object")
    return result


class Transport:
    """Delivers one JSON-RPC message and returns the matching response.

    :attr:`bytes_received` counts every byte read from the server, including
    exchanges that failed, so a caller can charge them to a budget.
    """

    bytes_received = 0

    def send(
        self,
        message: Dict[str, Any],
        *,
        headers: Mapping[str, str],
        timeout: float,
        limit: int = MAX_MESSAGE_BYTES,
    ) -> Optional[Mapping[str, Any]]:
        """The response to *message*, or ``None`` for a notification.

        The exchange gives up once *timeout* seconds have passed, and
        receiving more than *limit* bytes raises :class:`McpSizeError`.
        """
        raise NotImplementedError

    def close(self) -> None:
        """Release the connection or child process."""


class StdioTransport(Transport):
    """Newline-delimited JSON-RPC over a child process's stdin and stdout.

    Reads and writes each run on their own thread, so a server that stops
    reading its input or stops writing its output cannot block a request
    past its deadline. On POSIX the server starts in its own session, so
    shutdown also reaches a launcher's children (``npx`` and ``uvx`` run the
    real server as one).
    """

    def __init__(self, command: List[str], *, env: Optional[Dict[str, str]] = None, cwd=None):
        if not command:
            raise McpError("empty server command")
        try:
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=env,
                cwd=cwd,
                start_new_session=os.name == "posix",
            )
        except OSError as exc:
            raise McpError(f"could not start {command[0]!r}: {exc.strerror or exc}") from exc
        except ValueError as exc:
            # A NUL in the command, an argument, the environment or the working
            # directory; not quoted, as any of them may carry a credential.
            raise McpError(
                "could not start the server: its command, arguments, environment or working "
                "directory hold a character the system refuses"
            ) from exc
        # Bounded in messages and bytes, so a server that floods stdout
        # blocks instead of filling memory; the reader gives up waiting for
        # room once closing starts.
        self._messages: "queue.Queue[Optional[Tuple[Any, int]]]" = queue.Queue(_STDIO_BACKLOG)
        self._room = threading.Condition()
        self._backlog_bytes = 0
        # What the current request may receive; the reader never takes more
        # of a line, so a small byte budget also bounds what is read ahead.
        self._line_limit = MAX_MESSAGE_BYTES
        self._outbox: "queue.Queue[Optional[Tuple[bytes, threading.Event]]]" = queue.Queue()
        self._closing = threading.Event()
        self._exited = False
        self._input_broken = False  # the server closed its input
        self._input_stalled = False  # a write outlived its deadline
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._writer = threading.Thread(target=self._write_all, daemon=True)
        self._reader.start()
        self._writer.start()

    def _read_line(self, stdout) -> bytes:
        """The next line, or as much of it as the current request may receive, plus a byte.

        Read in chunks so a limit lowered while a read is waiting still
        applies; empty at the end of output.
        """
        line = bytearray()
        while True:
            room = self._line_limit + 1 - len(line)
            piece = stdout.readline(max(1, min(_READ_CHUNK, room)))
            line += piece
            if not piece or piece.endswith(b"\n") or len(line) > self._line_limit:
                return bytes(line)

    def _read(self) -> None:
        stdout = self._process.stdout
        assert stdout is not None
        try:
            while True:
                line = self._read_line(stdout)
                if not line:
                    break
                try:
                    message = _loads(line)
                except ValueError:
                    message = _NOISE  # servers sometimes log to stdout
                except McpError as exc:
                    message = exc  # raised when the caller reaches it
                if not self._put((message, len(line))):
                    return
        except (OSError, ValueError):
            pass  # the pipe went away during shutdown
        finally:
            self._put(None)

    def _put(self, item: Optional[Tuple[Any, int]]) -> bool:
        """Queue *item*, waiting for room until the transport closes.

        Past the first message, the backlog holds at most what the current
        request may receive: the byte budget is charged only as messages are
        taken, so it cannot bound what waits here.
        """
        size = 0 if item is None else item[1]
        with self._room:
            while self._backlog_bytes and self._backlog_bytes + size > self._line_limit:
                if self._closing.is_set():
                    return False
                self._room.wait(0.1)
            self._backlog_bytes += size
        while not self._closing.is_set():
            try:
                self._messages.put(item, timeout=0.1)
                return True
            except queue.Full:
                continue
        return False

    def _write_all(self) -> None:
        stdin = self._process.stdin
        assert stdin is not None
        while True:
            item = self._outbox.get()
            if item is None:
                return
            data, written = item
            if not self._input_broken:
                try:
                    stdin.write(data)
                    stdin.flush()
                except (OSError, ValueError):
                    self._input_broken = True
            written.set()

    def _write(self, message: Mapping[str, Any], deadline: float, timeout: float) -> None:
        if self._input_stalled:
            raise McpError("server stopped reading its input")
        written = threading.Event()
        self._outbox.put((json.dumps(message).encode("utf-8") + b"\n", written))
        if not written.wait(max(0.0, deadline - time.monotonic())):
            # The writer stays blocked until the server reads or exits;
            # nothing more can be sent in order behind it.
            self._input_stalled = True
            raise McpTimeoutError(
                f"timed out after {timeout:g}s: the server stopped reading its input"
            )
        if self._input_broken:
            raise McpError("server process closed its input")

    def send(self, message, *, headers, timeout, limit=MAX_MESSAGE_BYTES):
        if self._exited:
            raise McpError("server process exited")
        method = message.get("method", "a reply")
        self._line_limit = min(limit, MAX_MESSAGE_BYTES)
        # One deadline for the exchange: neither a slow write nor
        # notifications arriving first may extend it.
        deadline = time.monotonic() + timeout
        self._write(message, deadline, timeout)
        request_id = message.get("id")
        if request_id is None:
            return None
        received = 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _timed_out(timeout, method)
            try:
                item = self._messages.get(timeout=remaining)
            except queue.Empty:
                raise _timed_out(timeout, method) from None
            if item is None:
                self._exited = True
                raise McpError("server process exited")
            incoming, size = item
            with self._room:
                self._backlog_bytes -= size
                self._room.notify()
            received += size
            self.bytes_received += size
            if received > limit:
                raise McpSizeError(f"the response to {method} exceeded {limit} bytes")
            if isinstance(incoming, McpError):
                raise incoming
            response = _response_for(incoming, request_id)
            if response is not None:
                return response
            # A legacy server may ask the client something: answer a ping,
            # and refuse anything else (roots/list) rather than leave it waiting.
            if isinstance(incoming, Mapping) and "method" in incoming and "id" in incoming:
                reply: Dict[str, Any] = {"jsonrpc": "2.0", "id": incoming["id"]}
                if incoming["method"] == "ping":
                    reply["result"] = {}
                else:
                    reply["error"] = {"code": -32601, "message": "Method not found"}
                self._write(reply, deadline, timeout)

    def close(self) -> None:
        """Shut the server down the way the stdio transport specifies.

        Close its input and let it exit, then escalate to SIGTERM and
        SIGKILL. A pipe is closed only once its thread has finished: closing
        it under a blocked read or write waits on the buffer's lock, and a
        grandchild that outlived the server can hold either pipe open
        forever. Both threads are daemons, so one still blocked is left
        behind rather than waited on.
        """
        self._closing.set()
        self._outbox.put(None)
        self._writer.join(timeout=0.1)
        # A writer blocked on a server that stopped reading cannot close
        # stdin, so skip straight to signals.
        if not (self._close_stdin() and self._exit_within(_EXIT_GRACE)):
            self._signal(signal.SIGTERM)
            if not self._exit_within(_EXIT_GRACE):
                self._signal(getattr(signal, "SIGKILL", signal.SIGTERM))
                self._exit_within(_EXIT_GRACE)
        self._writer.join(timeout=0.5)
        self._reader.join(timeout=0.5)
        if os.name == "posix" and (self._reader.is_alive() or self._writer.is_alive()):
            self._signal(signal.SIGKILL, group_only=True)
            self._writer.join(timeout=0.5)
            self._reader.join(timeout=0.5)
        self._close_stdin()
        if not self._reader.is_alive() and self._process.stdout is not None:
            try:
                self._process.stdout.close()
            except OSError:
                pass

    def _close_stdin(self) -> bool:
        """Close the server's input unless the writer is still using it."""
        stdin = self._process.stdin
        if stdin is None or self._writer.is_alive():
            return False
        try:
            stdin.close()
        except OSError:
            pass
        return True

    def _exit_within(self, seconds: float) -> bool:
        try:
            self._process.wait(timeout=seconds)
            return True
        except subprocess.TimeoutExpired:
            return False

    def _signal(self, signum: int, *, group_only: bool = False) -> None:
        """Signal the server's process group, or just the server off POSIX."""
        if os.name == "posix":
            try:
                os.killpg(self._process.pid, signum)
                return
            except OSError:
                if group_only:
                    return
        try:
            if signum == signal.SIGTERM:
                self._process.terminate()
            else:
                self._process.kill()
        except OSError:
            pass


_SSE_LINE_END = re.compile(rb"\r\n|\r|\n")
_BOM = b"\xef\xbb\xbf"


def _sse_messages(
    stream, *, deadline: float, timeout: float, method: str, limit: int
) -> Iterator[Tuple[Any, int]]:
    """JSON payloads of a ``text/event-stream`` body, with the bytes read so far.

    Parsed as the SSE standard says: lines end in CRLF, LF or a bare CR, a
    leading BOM is dropped, and each ``data`` field adds a line to the event
    a blank line dispatches. The body is consumed in bounded pieces, so
    neither a line without an end nor a stream that never closes can outgrow
    *limit* or outlast *deadline*.
    """
    read = _chunk_reader(stream)
    pending = bytearray()
    data: List[bytes] = []
    total = 0
    started = False
    skip_lf = False  # the last read ended in CR; an LF opening the next is its pair
    scanned = 0  # bytes of *pending* already searched, so a long line stays linear
    eof = False
    while not eof:
        _check_deadline(deadline, timeout, method)
        chunk = read(min(_READ_CHUNK, limit + 1 - total))
        if chunk:
            total += len(chunk)
            if total > limit:
                raise McpSizeError(f"the event stream for {method} exceeded {limit} bytes")
            pending += chunk
        else:
            eof = True
            pending += b"\n\n"  # dispatch an event the stream did not finish
        if not started:
            if len(pending) < len(_BOM) and not eof and _BOM.startswith(bytes(pending)):
                continue  # too short to tell whether it opens with a BOM
            if pending.startswith(_BOM):
                del pending[: len(_BOM)]
            started = True
        if skip_lf and pending:
            if pending.startswith(b"\n"):
                del pending[:1]
            skip_lf = False
        start = 0
        while True:
            end = _SSE_LINE_END.search(pending, max(start, scanned))
            if end is None:
                break
            # A CR ends its line at once, so an event the server sends
            # whole is dispatched without waiting on the next read.
            skip_lf = end.group() == b"\r" and end.end() == len(pending)
            line = bytes(pending[start : end.start()])
            start = end.end()
            if not line:
                if data:
                    try:
                        yield _loads(b"\n".join(data)), total
                    except ValueError:
                        pass
                    data = []
                continue
            name, colon, value = line.partition(b":")
            if name == b"data":
                data.append(value[1:] if colon and value.startswith(b" ") else value)
        del pending[:start]
        scanned = len(pending)


_RETRY_SECONDS = re.compile(r"[0-9]{1,6}")


def _busy_delay(exc: urllib.error.HTTPError, attempt: int, deadline: float) -> Optional[float]:
    """Seconds to wait before retrying a busy server, or ``None`` to give up."""
    if exc.code not in (429, 503) or attempt >= _BUSY_RETRIES:
        return None
    delay = 2.0**attempt
    retry_after = (exc.headers.get("Retry-After") or "").strip() if exc.headers else ""
    if _RETRY_SECONDS.fullmatch(retry_after):
        delay = float(retry_after)  # an HTTP-date keeps the doubling delay
    if time.monotonic() + delay >= deadline:
        return None
    return delay


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    """Treat a redirect as an error rather than following it.

    urllib re-sends the request's headers to the redirect target, so a
    server could bounce a user's ``Authorization`` header to another host.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _Watchdog:
    """Shuts a request's sockets down when its deadline passes.

    A socket timeout bounds each read, not the exchange: a server that
    drips a header, a TLS record or a chunk-size line a byte at a time never
    trips it. Shutting the socket down from a timer interrupts whatever read
    is in progress, so the deadline holds for the whole exchange.
    """

    def __init__(self, seconds: float):
        self.deadline = time.monotonic() + seconds
        self.fired = False
        self._sockets: List[socket.socket] = []
        self._lock = threading.Lock()
        self._timer = threading.Timer(seconds, self._fire)
        self._timer.daemon = True
        self._timer.start()

    def remaining(self) -> float:
        return max(0.001, self.deadline - time.monotonic())

    def watch(self, sock: socket.socket) -> None:
        with self._lock:
            if not self.fired:
                self._sockets.append(sock)
                return
        _shut_down(sock)

    def _fire(self) -> None:
        with self._lock:
            self.fired = True
            sockets, self._sockets = self._sockets, []
        for sock in sockets:
            _shut_down(sock)

    def cancel(self) -> None:
        self._timer.cancel()
        with self._lock:
            self._sockets = []


def _shut_down(sock: socket.socket) -> None:
    try:
        # The plain socket's method, so a TLS socket is cut at the transport
        # without touching the SSL object another thread may be using.
        socket.socket.shutdown(sock, socket.SHUT_RDWR)
    except OSError:
        pass  # already closed, or detached when TLS wrapped it


def _resolve_within(watchdog: _Watchdog, host: str, port: int) -> List[Tuple[Any, ...]]:
    """``getaddrinfo`` inside the deadline.

    A stalled resolver cannot be interrupted, so it runs on a daemon thread
    that is left behind if the deadline passes first.
    """
    outcome: Dict[str, Any] = {}

    def resolve() -> None:
        try:
            outcome["addresses"] = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
        except Exception as exc:  # re-raised on the caller's thread
            outcome["error"] = exc

    resolver = threading.Thread(target=resolve, daemon=True)
    resolver.start()
    resolver.join(max(0.0, watchdog.deadline - time.monotonic()))
    if resolver.is_alive():
        raise socket.timeout("timed out resolving the server's address")
    if "error" in outcome:
        raise outcome["error"]
    return outcome["addresses"]


def _connect_within(watchdog: _Watchdog, address, timeout=None, source_address=None):
    """:func:`socket.create_connection`, with every attempt inside the deadline.

    The standard function gives each resolved address the full timeout, so
    a host with several unreachable addresses could outlast the deadline
    many times over. Each socket is watched before it connects, and each
    attempt gets only the time left, and so does name resolution.
    """
    host, port = address
    if not isinstance(timeout, (int, float)):
        timeout = socket.getdefaulttimeout()
    error: OSError = OSError("getaddrinfo returns an empty list")
    for family, kind, proto, _, sockaddr in _resolve_within(watchdog, host, port):
        if watchdog.fired or time.monotonic() >= watchdog.deadline:
            raise socket.timeout("timed out")
        sock = None
        try:
            # Inside the try: a family the host lacks (IPv6 in many
            # containers) fails here, and the next address should be tried.
            sock = socket.socket(family, kind, proto)
            watchdog.watch(sock)
            sock.settimeout(watchdog.remaining())
            if source_address:
                sock.bind(source_address)
            sock.connect(sockaddr)
        except OSError as exc:
            error = exc
            if sock is not None:
                sock.close()
            continue
        sock.settimeout(timeout)
        return sock
    raise error


class _WatchedHTTPConnection(http.client.HTTPConnection):
    """An HTTP connection whose socket a :class:`_Watchdog` can cut."""

    def __init__(self, *args, watchdog: _Watchdog, **kwargs):
        super().__init__(*args, **kwargs)
        self._watchdog = watchdog
        # Watched before it connects, and before any proxy CONNECT exchange.
        self._create_connection = functools.partial(_connect_within, watchdog)


if hasattr(http.client, "HTTPSConnection"):

    class _WatchedHTTPSConnection(_WatchedHTTPConnection, http.client.HTTPSConnection):
        """HTTPS, with the TLS socket watched before its handshake runs."""

        def connect(self):
            http.client.HTTPConnection.connect(self)
            server_hostname = self._tunnel_host or self.host
            self.sock = self._context.wrap_socket(
                self.sock, server_hostname=server_hostname, do_handshake_on_connect=False
            )
            self._watchdog.watch(self.sock)
            self.sock.do_handshake()


class _WatchedOpen:
    """Open a request through a watched connection when it carries a watchdog."""

    def do_open(self, http_class, req, **kwargs):
        watchdog = getattr(req, "watchdog", None)
        if watchdog is not None:
            https = hasattr(http.client, "HTTPSConnection") and issubclass(
                http_class, http.client.HTTPSConnection
            )
            watched = _WatchedHTTPSConnection if https else _WatchedHTTPConnection
            http_class = functools.partial(watched, watchdog=watchdog)
        return super().do_open(http_class, req, **kwargs)  # type: ignore[misc]


class _WatchedHTTPHandler(_WatchedOpen, urllib.request.HTTPHandler):
    pass


_HANDLERS: List[Any] = [_RefuseRedirects, _WatchedHTTPHandler]
if hasattr(urllib.request, "HTTPSHandler"):

    class _WatchedHTTPSHandler(_WatchedOpen, urllib.request.HTTPSHandler):
        pass

    _HANDLERS.append(_WatchedHTTPSHandler)

_OPENER = urllib.request.build_opener(*_HANDLERS)


def _header_bytes(headers: Any, reason: Any = "") -> int:
    """Roughly the bytes a status line and *headers* took on the wire.

    The reason phrase is counted too: ``http.client`` accepts nearly 64 KiB
    of it on every response.
    """
    if headers is None:
        return 0
    status_line = 16 + len(reason if isinstance(reason, str) else "")
    return status_line + sum(len(name) + len(value) + 4 for name, value in headers.items())


class _Counted:
    """A response body that adds what is read from it to a transport's count."""

    def __init__(self, stream, transport: Transport):
        self._read = _chunk_reader(stream)
        self._transport = transport

    def read1(self, n: int) -> bytes:
        chunk = self._read(n)
        self._transport.bytes_received += len(chunk)
        return chunk


class HttpTransport(Transport):
    """JSON-RPC over Streamable HTTP, accepting JSON or SSE responses."""

    def __init__(self, url: str, *, headers: Optional[Mapping[str, str]] = None):
        if not url.lower().startswith(("http://", "https://")):
            raise McpError("server URL must use http or https")
        self.url = url
        self.headers = dict(headers or {})
        self.session_id: Optional[str] = None
        self.bytes_received = 0

    def send(self, message, *, headers, timeout, limit=MAX_MESSAGE_BYTES):
        watchdog = _Watchdog(timeout)
        try:
            return self._exchange(message, headers, watchdog, timeout, limit)
        except McpSizeError:
            raise
        except (McpError, OSError, http.client.HTTPException) as exc:
            # Not remaining(), which never reaches 0: a socket timeout can
            # land at the deadline before the timer thread runs.
            if watchdog.fired or time.monotonic() >= watchdog.deadline:
                raise _timed_out(timeout, message["method"]) from exc
            raise
        finally:
            watchdog.cancel()

    def _exchange(self, message, headers, watchdog: _Watchdog, timeout: float, limit: int):
        method = message["method"]
        body = json.dumps(message).encode("utf-8")
        request = urllib.request.Request(self.url, data=body, method="POST")
        request.add_header("Content-Type", "application/json")
        request.add_header("Accept", "application/json, text/event-stream")
        for name, value in {**self.headers, **headers}.items():
            request.add_header(name, value)
        if self.session_id:
            request.add_header("Mcp-Session-Id", self.session_id)
        request.watchdog = watchdog  # type: ignore[attr-defined]
        bounds = {"deadline": watchdog.deadline, "timeout": timeout, "method": method}
        attempt = 0
        while True:
            try:
                response = _OPENER.open(request, timeout=watchdog.remaining())
                break
            except urllib.error.HTTPError as exc:
                self.bytes_received += _header_bytes(exc.headers, exc.reason)
                delay = _busy_delay(exc, attempt, watchdog.deadline)
                if delay is None:
                    return self._error_status(exc, message, bounds, limit)
                exc.close()
                time.sleep(delay)
                attempt += 1
            except (ValueError, http.client.InvalidURL) as exc:
                # Their messages can quote the URL or a header value, and so a
                # credential; errors reach the terminal and the snapshot.
                raise McpError(
                    "could not send the request: the URL or a header is not valid HTTP"
                ) from exc
            except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
                reason = getattr(exc, "reason", exc)
                raise McpError(f"could not reach server: {reason}") from exc
        self.bytes_received += _header_bytes(response.headers, response.reason)
        # Reading the body can fail or stall after the headers arrived; that
        # is the server's failure too, not the caller's.
        try:
            with response:
                return self._consume(response, message, bounds, limit)
        except (OSError, http.client.HTTPException) as exc:
            raise McpError(f"reading the response to {method} failed: {exc}") from exc

    def _error_status(self, exc, message, bounds, limit):
        """A JSON-RPC error carried by a 4xx/5xx status, or an :class:`McpError`."""
        # The era probe needs a modern refusal's error body to tell it from
        # a legacy server. An oversized or stalled body is still an error
        # (and still counted), not a reason to ignore the status.
        try:
            with exc:
                payload = _read_body(_Counted(exc, self), limit=limit, **bounds)
        except (OSError, http.client.HTTPException):
            payload = b""
        try:
            parsed = _loads(payload)
        except (ValueError, McpError):
            parsed = None
        if exc.code == 401:
            raise McpAuthError("the server requires authorization (HTTP 401)") from exc
        if isinstance(parsed, Mapping) and "error" in parsed:
            return {"jsonrpc": "2.0", "id": message.get("id"), "error": parsed["error"]}
        if 300 <= exc.code < 400:
            raise McpError(f"HTTP {exc.code} redirect refused; use the final server URL") from exc
        raise McpError(f"HTTP {exc.code} from server") from exc

    def _consume(self, response, message, bounds, limit):
        session = response.headers.get("Mcp-Session-Id")
        if session:
            self.session_id = session
        request_id = message.get("id")
        if request_id is None:
            return None
        method = message["method"]
        body = _Counted(response, self)
        content_type = (response.headers.get("Content-Type") or "").lower()
        if content_type.startswith("text/event-stream"):
            for incoming, _ in _sse_messages(body, limit=limit, **bounds):
                found = _response_for(incoming, request_id)
                if found is not None:
                    return found
            raise McpError(f"event stream ended without a response to {method}")
        payload = _read_body(body, limit=limit, **bounds)
        try:
            parsed = _loads(payload)
        except ValueError as exc:
            raise McpError("server returned a non-JSON response") from exc
        found = _response_for(parsed, request_id)
        if found is None:
            raise McpError(f"server returned no response to {method}")
        return found


@dataclass
class ServerInfo:
    """What the server told us about itself while connecting."""

    protocol_version: str
    modern: bool
    capabilities: Dict[str, Any] = field(default_factory=dict)
    server_info: Optional[Dict[str, Any]] = None

    @property
    def skills_extension(self) -> Optional[Dict[str, Any]]:
        extensions = self.capabilities.get("extensions")
        if isinstance(extensions, Mapping):
            settings = extensions.get(EXTENSION_ID)
            if isinstance(settings, Mapping):
                return dict(settings)
        return None


class McpSession:
    """One connection to one server, negotiated into either protocol era.

    With *max_bytes*, every response counts against that budget, and a
    request that would need more than is left raises
    :class:`McpBudgetError`. :attr:`requests` counts the requests sent.
    """

    def __init__(
        self, transport: Transport, *, timeout: float = 30.0, max_bytes: Optional[int] = None
    ):
        self.transport = transport
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.received = 0
        self.requests = 0
        self.info: Optional[ServerInfo] = None
        self._ids = itertools.count(1)

    def close(self) -> None:
        self.transport.close()

    def _meta(self, version: str) -> Dict[str, Any]:
        return {
            "io.modelcontextprotocol/protocolVersion": version,
            "io.modelcontextprotocol/clientInfo": _client_info(),
            "io.modelcontextprotocol/clientCapabilities": CLIENT_CAPABILITIES,
        }

    def _budget_error(self) -> McpBudgetError:
        return McpBudgetError(f"the byte budget of {self.max_bytes} bytes was reached")

    def _send(
        self,
        method: str,
        params: Dict[str, Any],
        *,
        modern: bool,
        version: str,
        notification: bool = False,
    ):
        limit = MAX_MESSAGE_BYTES
        budget_bound = False
        if self.max_bytes is not None:
            left = self.max_bytes - self.received
            if left <= 0:
                raise self._budget_error()
            budget_bound = left <= limit
            limit = min(limit, left)
        message: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if not notification:
            message["id"] = next(self._ids)
        headers: Dict[str, str] = {}
        if modern:
            params = {**params, "_meta": self._meta(version)}
            headers["MCP-Protocol-Version"] = version
            headers["Mcp-Method"] = method
            name = params.get("uri") or params.get("name")
            if isinstance(name, str):
                headers["Mcp-Name"] = _header_value(name)
        elif version not in ("2024-11-05", "2025-03-26") and method != "initialize":
            headers["MCP-Protocol-Version"] = version
        message["params"] = params
        self.requests += 1
        before = self.transport.bytes_received
        try:
            response = self.transport.send(
                message, headers=headers, timeout=self.timeout, limit=limit
            )
        except McpSizeError:
            if budget_bound:
                self.received = self.max_bytes or 0
                raise self._budget_error() from None
            raise
        finally:
            # Failed exchanges cost bytes too; charge whatever was read.
            self.received += self.transport.bytes_received - before
        if notification:
            return {}
        assert response is not None
        return _unwrap(response)

    def connect(self) -> ServerInfo:
        """Probe for a modern server, falling back to the legacy handshake."""
        try:
            result = self._send("server/discover", {}, modern=True, version=MODERN_VERSION)
        except McpRpcError as exc:
            if exc.code not in MODERN_ERROR_CODES:
                return self._initialize(LEGACY_VERSIONS[0])
            supported = exc.data.get("supported") if isinstance(exc.data, Mapping) else None
            legacy = [v for v in LEGACY_VERSIONS if isinstance(supported, list) and v in supported]
            if exc.code == UNSUPPORTED_VERSION and legacy:
                return self._initialize(legacy[0])
            raise McpError(f"server refused protocol {MODERN_VERSION}: {exc.rpc_message}")
        except (McpBudgetError, McpAuthError):
            raise  # neither means a legacy server
        except McpError as probe:
            # A timeout or transport failure may mean a legacy server, so try
            # the handshake — but if that fails too, the probe's failure is
            # usually the one that explains it.
            try:
                return self._initialize(LEGACY_VERSIONS[0])
            except McpBudgetError:
                raise
            except McpError as exc:
                if str(exc) == str(probe):
                    raise
                raise McpError(
                    f"server/discover failed ({probe}), then initialize failed ({exc})"
                ) from exc
        versions = result.get("supportedVersions")
        if not isinstance(versions, list) or MODERN_VERSION not in versions:
            legacy = [v for v in LEGACY_VERSIONS if isinstance(versions, list) and v in versions]
            if legacy:
                return self._initialize(legacy[0])
            raise McpError(f"server supports none of this client's versions: {versions!r}")
        meta = result.get("_meta")
        server_info = (
            meta.get("io.modelcontextprotocol/serverInfo") if isinstance(meta, Mapping) else None
        )
        capabilities = result.get("capabilities")
        self.info = ServerInfo(
            protocol_version=MODERN_VERSION,
            modern=True,
            capabilities=dict(capabilities) if isinstance(capabilities, Mapping) else {},
            server_info=dict(server_info) if isinstance(server_info, Mapping) else None,
        )
        return self.info

    def _initialize(self, version: str) -> ServerInfo:
        result = self._send(
            "initialize",
            {
                "protocolVersion": version,
                "capabilities": CLIENT_CAPABILITIES,
                "clientInfo": _client_info(),
            },
            modern=False,
            version=version,
        )
        negotiated = result.get("protocolVersion")
        if not isinstance(negotiated, str):
            raise McpError("initialize result has no protocolVersion")
        if negotiated not in LEGACY_VERSIONS:
            # The handshake says to disconnect rather than guess at its shapes.
            raise McpError(
                f"server chose protocol version {negotiated[:40]!r}, which is not supported"
            )
        # A failed notification is the server's problem, unless what it sent
        # back spent the budget.
        try:
            self._send(
                "notifications/initialized",
                {},
                modern=False,
                version=negotiated,
                notification=True,
            )
        except McpBudgetError:
            raise
        except McpError:
            pass
        capabilities = result.get("capabilities")
        server_info = result.get("serverInfo")
        self.info = ServerInfo(
            protocol_version=negotiated,
            modern=False,
            capabilities=dict(capabilities) if isinstance(capabilities, Mapping) else {},
            server_info=dict(server_info) if isinstance(server_info, Mapping) else None,
        )
        return self.info

    def request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Send one request in the negotiated era and return its result."""
        if self.info is None:
            raise McpError("not connected")
        return self._send(
            method,
            dict(params or {}),
            modern=self.info.modern,
            version=self.info.protocol_version,
        )

    def iter_skills(self, *, max_pages: int = 1000) -> Iterator[Any]:
        """The entries ``skills/list`` returns, requesting each page on demand.

        A caller that stops iterating stops the pagination with it, so a
        server listing more skills than wanted is never read to the end.
        """
        cursor: Optional[str] = None
        for _ in range(max_pages):
            result = self.request("skills/list", {"cursor": cursor} if cursor else {})
            skills = result.get("skills")
            if not isinstance(skills, list):
                raise McpError("skills/list result has no 'skills' array")
            yield from skills
            next_cursor = result.get("nextCursor")
            if next_cursor is None or next_cursor == "":
                return
            if not isinstance(next_cursor, str):
                # Ending here would drop the rest of the listing in silence.
                raise McpError("skills/list returned a nextCursor that is not a string")
            cursor = next_cursor
        raise McpError(f"skills/list did not finish within {max_pages} pages")

    def read_resource(self, uri: str) -> bytes:
        """The raw bytes ``resources/read`` returns for *uri*."""
        result = self.request("resources/read", {"uri": uri})
        contents = result.get("contents")
        if not isinstance(contents, list) or not contents:
            raise McpError("resources/read returned no contents")
        match = next((c for c in contents if isinstance(c, Mapping) and c.get("uri") == uri), None)
        if match is None:
            # A lone entry naming no URI can only be the one asked for; any
            # other answer would be stored as this file without a check.
            only = contents[0] if len(contents) == 1 else None
            if not isinstance(only, Mapping):
                raise McpError("resources/read returned malformed contents")
            if "uri" in only:
                raise McpError("resources/read returned contents for a different URI")
            match = only
        if isinstance(match.get("text"), str):
            try:
                return match["text"].encode("utf-8")
            except UnicodeEncodeError as exc:  # an escaped unpaired surrogate
                raise McpError("resources/read returned text that is not valid Unicode") from exc
        if isinstance(match.get("blob"), str):
            try:
                return base64.b64decode(match["blob"], validate=True)
            except ValueError as exc:
                raise McpError("resources/read returned invalid base64") from exc
        raise McpError("resources/read contents carry neither text nor blob")

    def read_directory(
        self, uri: str, *, max_pages: int = 100, max_entries: int = 1024
    ) -> Tuple[List[Mapping[str, Any]], bool]:
        """Children of a directory resource (``directoryRead`` servers).

        Returns the children and whether the listing is complete; it stops
        early, incomplete, after *max_pages* requests or *max_entries*
        children.
        """
        children: List[Mapping[str, Any]] = []
        cursor: Optional[str] = None
        for _ in range(max_pages):
            params: Dict[str, Any] = {"uri": uri}
            if cursor:
                params["cursor"] = cursor
            result = self.request("resources/directory/read", params)
            resources = result.get("resources")
            if not isinstance(resources, list):
                raise McpError("resources/directory/read result has no 'resources' array")
            for item in resources:
                if len(children) >= max_entries:
                    return children, False
                if not isinstance(item, Mapping):
                    # Skipping it could leave a file out of a listing called complete.
                    raise McpError("resources/directory/read listed an entry that is not an object")
                children.append(item)
            next_cursor = result.get("nextCursor")
            if next_cursor is None or next_cursor == "":
                return children, True
            if not isinstance(next_cursor, str):
                raise McpError(
                    "resources/directory/read returned a nextCursor that is not a string"
                )
            cursor = next_cursor
        return children, False

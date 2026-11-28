"""MCP client adapter for fetching served skills (SEP-2640).

Delegates protocol negotiation (modern ``2026-07-28`` via ``server/discover``
with automatic fallback to legacy ``initialize``), Streamable HTTP / SSE
framing, and stdio process-tree management to the official ``mcp`` Python SDK
(installed via the optional ``skillsaw[mcp]`` extra).

This module adds the inspector policy skillsaw needs on top of the SDK:

* lazy SDK import so base ``skillsaw`` has no MCP runtime dependency;
* refusing HTTP 401 and 3xx redirects before reading the body or falling back;
* bounded HTTP 429/503 retries honoring ``Retry-After``;
* a per-session byte budget across HTTP wire bytes (including error responses)
  and stdio payloads, plus per-request timeouts;
* loopback ``http://`` proxy bypass;
* SEP-2640 request helpers (``skills/list``, ``resources/read``,
  ``resources/directory/read``) with modern ``CacheableResult`` validation.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from collections.abc import AsyncIterator, Mapping
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple
from urllib.parse import urlsplit

from .diagnostics import safe_display
from .formats.mcp_skills import EXTENSION_ID, is_loopback_host

#: Cap on one resource-read message (fits a 16 MiB base64 blob or heavily
#: JSON-escaped 16 MiB text file plus envelope; decoded size is enforced too).
MAX_MESSAGE_BYTES = 36 * 1024 * 1024
#: Retries of a request a busy server (HTTP 429 or 503) turned away.
_BUSY_RETRIES = 3

_INSTALL_HINT = (
    "fetching skills from MCP servers requires the optional 'mcp' extra; "
    "install it with: pip install 'skillsaw[mcp]' "
    "(or run with: uvx --from 'skillsaw[mcp]' skillsaw ...)"
)


class McpError(Exception):
    """The server could not be reached or broke the protocol."""


class McpMissingDependencyError(McpError):
    """The optional ``skillsaw[mcp]`` dependency is not installed."""


class McpSizeError(McpError):
    """A response was larger than the caller allowed."""


class McpBudgetError(McpError):
    """The session's byte budget is spent."""


class McpAuthError(McpError):
    """The server wants credentials the request did not carry (HTTP 401)."""


class McpTimeoutError(McpError):
    """A request outlived its deadline: the server stopped answering."""


class McpRedirectError(McpError):
    """The server answered with an HTTP redirect, which is refused."""


class McpRpcError(McpError):
    """The server answered a request with a JSON-RPC error."""

    def __init__(self, code: Any, message: Any, data: Any = None):
        super().__init__(f"{message} (code {code})")
        self.code = code if isinstance(code, int) and not isinstance(code, bool) else None
        self.rpc_message = message
        self.data = data


@dataclass(frozen=True)
class _Sdk:
    anyio: Any
    httpx2: Any
    types: Any
    pydantic: Any
    Client: Any
    advertise: Any
    StdioServerParameters: Any
    stdio_client: Any
    streamable_http_client: Any
    MCPError: Any
    ClientMessageMetadata: Any
    MCP_NAME_HEADER: str
    encode_header_value: Any
    SkillsListRequest: Any
    ReadResourceRawRequest: Any
    DirectoryReadRequest: Any
    dict_adapter: Any


@lru_cache(maxsize=1)
def _load_sdk() -> _Sdk:
    try:
        import anyio
        import httpx2
        import mcp_types as types
        import pydantic
        from mcp import Client
        from mcp.client.extension import advertise
        from mcp.client.stdio import StdioServerParameters, stdio_client
        from mcp.client.streamable_http import streamable_http_client
        from mcp.shared.exceptions import MCPError
        from mcp.shared.inbound import MCP_NAME_HEADER, encode_header_value
        from mcp.shared.message import ClientMessageMetadata
    except ModuleNotFoundError as exc:
        raise McpMissingDependencyError(_INSTALL_HINT) from exc

    class _SkillsListRequest(types.Request[dict[str, Any], Literal["skills/list"]]):
        method: Literal["skills/list"] = "skills/list"
        params: dict[str, Any] = {}

    class _ReadResourceRawRequest(types.Request[dict[str, Any], Literal["resources/read"]]):
        method: Literal["resources/read"] = "resources/read"
        params: dict[str, Any] = {}

    class _DirectoryReadRequest(types.Request[dict[str, Any], Literal["resources/directory/read"]]):
        method: Literal["resources/directory/read"] = "resources/directory/read"
        params: dict[str, Any] = {}

    # Keep SDK-internal parse/notification warnings from printing tracebacks to
    # stderr via Python's lastResort handler during CLI runs.
    for logger_name in ("mcp", "client"):
        sdk_logger = logging.getLogger(logger_name)
        if not sdk_logger.handlers:
            sdk_logger.addHandler(logging.NullHandler())
            sdk_logger.propagate = False

    return _Sdk(
        anyio=anyio,
        httpx2=httpx2,
        types=types,
        pydantic=pydantic,
        Client=Client,
        advertise=advertise,
        StdioServerParameters=StdioServerParameters,
        stdio_client=stdio_client,
        streamable_http_client=streamable_http_client,
        MCPError=MCPError,
        ClientMessageMetadata=ClientMessageMetadata,
        MCP_NAME_HEADER=MCP_NAME_HEADER,
        encode_header_value=encode_header_value,
        SkillsListRequest=_SkillsListRequest,
        ReadResourceRawRequest=_ReadResourceRawRequest,
        DirectoryReadRequest=_DirectoryReadRequest,
        dict_adapter=pydantic.TypeAdapter(dict[str, Any]),
    )


def require_mcp() -> None:
    """Ensure the optional ``skillsaw[mcp]`` dependency is installed."""
    _load_sdk()


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

    def skills_extension_errors(self) -> List[str]:
        """Protocol-level errors in how the server declared the Skills extension."""
        extensions = self.capabilities.get("extensions")
        if not isinstance(extensions, Mapping) or EXTENSION_ID not in extensions:
            return []
        settings = extensions[EXTENSION_ID]
        if not isinstance(settings, Mapping):
            return [f"{EXTENSION_ID} capability must be an object"]
        errors: List[str] = []
        if "directoryRead" in settings and not isinstance(settings["directoryRead"], bool):
            errors.append(f"{EXTENSION_ID} capability 'directoryRead' must be a boolean")
        if not isinstance(self.capabilities.get("resources"), Mapping):
            errors.append(
                f"server advertises {EXTENSION_ID} without the required 'resources' capability"
            )
        return errors


class _Budget:
    """Shared per-session byte budget and terminal-error latch."""

    def __init__(self, max_bytes: Optional[int]):
        self.max_bytes = max_bytes
        self.received = 0
        self.fatal_error: Optional[McpError] = None
        self.last_http_status: Optional[int] = None

    def budget_error(self) -> McpBudgetError:
        return McpBudgetError(f"the byte budget of {self.max_bytes} bytes was reached")

    def fail(self, error: McpError) -> McpError:
        if self.fatal_error is None:
            self.fatal_error = error
        return self.fatal_error

    def remaining(self) -> Optional[int]:
        if self.max_bytes is None:
            return None
        return max(0, self.max_bytes - self.received)

    def charge(self, amount: int) -> None:
        self.received += amount
        if self.max_bytes is not None and self.received > self.max_bytes:
            raise self.fail(self.budget_error())


def _retry_after_delay(headers: Any, attempt: int, remaining: float) -> Optional[float]:
    """Seconds to wait before retrying HTTP 429/503, or ``None`` to give up."""
    if attempt >= _BUSY_RETRIES or remaining <= 0:
        return None
    raw = (headers.get("retry-after") or "").strip()
    delay: Optional[float] = None
    if raw.isascii() and raw.isdigit():
        delay = float(int(raw))
    elif raw:
        try:
            when = parsedate_to_datetime(raw)
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            delay = max(0.0, (when - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            delay = None
    if delay is None:
        delay = float(2**attempt)
    return delay if delay < remaining else None


def _header_byte_estimate(response: Any) -> int:
    """Wire-size estimate for an HTTP status line and its response headers."""
    return 32 + sum(len(k) + len(v) + 4 for k, v in response.headers.raw)


def _build_http_client(
    sdk: _Sdk,
    url: str,
    headers: Mapping[str, str],
    timeout: float,
    budget: _Budget,
    current_method: List[str],
) -> Any:
    httpx2: Any = sdk.httpx2
    anyio: Any = sdk.anyio
    byte_stream_base: Any = httpx2.AsyncByteStream
    transport_base: Any = httpx2.AsyncBaseTransport

    class _CountedStream(byte_stream_base):
        def __init__(self, inner: Any):
            self._inner = inner

        async def __aiter__(self):
            try:
                async for chunk in self._inner:
                    budget.charge(len(chunk))
                    yield chunk
            except McpError:
                await self._inner.aclose()
                raise

        async def aclose(self) -> None:
            await self._inner.aclose()

    class _GuardedTransport(transport_base):
        def __init__(self, inner: Any):
            self._inner = inner

        async def handle_async_request(self, request: Any) -> Any:
            if request.method == "DELETE" and budget.fatal_error is not None:
                return httpx2.Response(405)
            is_post = request.method == "POST"
            deadline = time.monotonic() + timeout
            attempt = 0
            while True:
                if budget.fatal_error is not None:
                    raise budget.fatal_error
                try:
                    response = await self._inner.handle_async_request(request)
                except httpx2.TimeoutException as exc:
                    if is_post:
                        err = McpTimeoutError(
                            f"timed out after {timeout:g}s waiting for {current_method[0]}"
                        )
                        raise budget.fail(err) from exc
                    raise
                except httpx2.HTTPError as exc:
                    if is_post:
                        raise budget.fail(McpError(f"could not reach server: {exc}")) from exc
                    raise

                status = response.status_code
                try:
                    budget.charge(_header_byte_estimate(response))
                except McpBudgetError:
                    await response.aclose()
                    raise

                if is_post and status in (429, 503):
                    delay = _retry_after_delay(
                        response.headers, attempt, deadline - time.monotonic()
                    )
                    if delay is not None:
                        await response.aclose()
                        await anyio.sleep(delay)
                        attempt += 1
                        continue

                if is_post and status == 401:
                    await response.aclose()
                    raise budget.fail(McpAuthError("the server requires authorization (HTTP 401)"))
                if is_post and 300 <= status < 400:
                    await response.aclose()
                    raise budget.fail(
                        McpRedirectError(
                            f"HTTP {status} redirect refused; use the final server URL"
                        )
                    )

                raw_len = response.headers.get("content-length")
                declared: Optional[int] = None
                if raw_len and raw_len.strip().isascii() and raw_len.strip().isdigit():
                    declared = int(raw_len.strip())
                    rem = budget.remaining()
                    if rem is not None and declared > rem:
                        await response.aclose()
                        raise budget.fail(budget.budget_error())
                    if declared > MAX_MESSAGE_BYTES:
                        await response.aclose()
                        raise McpSizeError(
                            f"the response to {current_method[0]} exceeded {MAX_MESSAGE_BYTES} bytes"
                        )

                content_type = (response.headers.get("content-type") or "").lower()
                if is_post and status >= 400 and not content_type.startswith("application/json"):
                    # The SDK closes non-JSON 4xx/5xx responses without reading their body;
                    # still charge declared bytes so error floods spend the server's budget.
                    if declared:
                        try:
                            budget.charge(declared)
                        except McpBudgetError:
                            await response.aclose()
                            raise

                if is_post:
                    budget.last_http_status = status if status >= 400 and status != 404 else None

                return httpx2.Response(
                    status_code=status,
                    headers=response.headers,
                    stream=_CountedStream(response.stream),
                    extensions=response.extensions,
                )

        async def aclose(self) -> None:
            await self._inner.aclose()

    parts = urlsplit(url)
    direct = parts.scheme == "http" and is_loopback_host(parts.hostname or "")
    try:
        client = httpx2.AsyncClient(
            headers=dict(headers),
            timeout=httpx2.Timeout(timeout),
            max_redirects=0,
            trust_env=not direct,
        )
    except (ValueError, UnicodeEncodeError, httpx2.InvalidURL) as exc:
        raise McpError("could not send the request: the URL or a header is not valid HTTP") from exc
    client._transport = _GuardedTransport(client._transport)
    client._mounts = {
        pattern: _GuardedTransport(tr) if tr is not None else None
        for pattern, tr in client._mounts.items()
    }
    return client


def _iter_leaf_exceptions(exc: BaseException) -> List[BaseException]:
    if isinstance(exc, BaseExceptionGroup):
        leaves: List[BaseException] = []
        for sub in exc.exceptions:
            leaves.extend(_iter_leaf_exceptions(sub))
        return leaves
    return [exc]


def _translate_error(
    exc: BaseException,
    sdk: _Sdk,
    budget: _Budget,
    *,
    method: str,
    timeout: float,
) -> McpError:
    if budget.fatal_error is not None:
        return budget.fatal_error
    leaves = _iter_leaf_exceptions(exc)
    for leaf in leaves:
        if isinstance(leaf, McpError):
            return leaf
    for leaf in leaves:
        if isinstance(leaf, (TimeoutError, sdk.httpx2.TimeoutException)):
            return McpTimeoutError(f"timed out after {timeout:g}s waiting for {method}")
    for leaf in leaves:
        if isinstance(leaf, sdk.MCPError):
            if leaf.code == sdk.types.REQUEST_TIMEOUT:
                return McpTimeoutError(f"timed out after {timeout:g}s waiting for {method}")
            if leaf.code == sdk.types.INTERNAL_ERROR and budget.last_http_status is not None:
                return McpError(f"HTTP {budget.last_http_status} from server")
            if (
                leaf.code == sdk.types.PARSE_ERROR
                and "recursion" in (leaf.error.message or "").lower()
            ):
                return McpError("the server sent JSON nested too deeply to parse")
            return McpRpcError(leaf.code, leaf.error.message, leaf.error.data)
    for leaf in leaves:
        if isinstance(leaf, RecursionError):
            return McpError("the server sent JSON nested too deeply to parse")
        if isinstance(leaf, sdk.pydantic.ValidationError):
            text = str(leaf)
            if "recursion" in text.lower():
                return McpError("the server sent JSON nested too deeply to parse")
            return McpError(f"malformed response to {method}: {text.splitlines()[0]}")
        if isinstance(leaf, (sdk.httpx2.InvalidURL, UnicodeEncodeError)):
            return McpError("could not send the request: the URL or a header is not valid HTTP")
        if isinstance(leaf, (sdk.httpx2.HTTPError, OSError)):
            return McpError(f"could not reach server: {leaf}")
        if isinstance(leaf, RuntimeError):
            return McpError(str(leaf))
    return McpError(str(leaves[0]))


def _validate_cacheable_envelope(method: str, result: Mapping[str, Any]) -> None:
    """Validate modern (2026-07-28) CacheableResult envelope fields when present."""
    if "resultType" in result and result["resultType"] != "complete":
        raise McpError(
            f"{method} returned unsupported resultType {safe_display(result['resultType'])!r}"
        )
    if "ttlMs" in result:
        ttl = result["ttlMs"]
        if not isinstance(ttl, int) or isinstance(ttl, bool) or ttl < 0:
            raise McpError(f"{method} result has missing or invalid 'ttlMs'")
    if "cacheScope" in result and result["cacheScope"] not in ("public", "private"):
        raise McpError(f"{method} result has missing or invalid 'cacheScope'")


def _server_info_from_session(session: Any) -> ServerInfo:
    discover = session.discover_result
    modern = discover is not None
    if discover is not None and discover.result_type != "complete":
        raise McpError(
            f"server/discover returned unsupported resultType {safe_display(discover.result_type)!r}"
        )
    caps_obj = session.server_capabilities
    caps = caps_obj.model_dump(by_alias=True, exclude_none=True) if caps_obj is not None else {}
    raw_info = session.server_info
    info_dict = (
        {"name": raw_info.name, "version": raw_info.version} if raw_info is not None else None
    )
    return ServerInfo(
        protocol_version=session.protocol_version or "",
        modern=modern,
        capabilities=caps,
        server_info=info_dict,
    )


class McpSession:
    """Connected MCP session exposing SEP-2640 skill listing and reads."""

    def __init__(
        self,
        *,
        sdk: _Sdk,
        session: Any,
        info: ServerInfo,
        budget: _Budget,
        timeout: float,
        current_method: List[str],
        count_response_bytes: bool,
    ):
        self._sdk = sdk
        self._session = session
        self.info = info
        self._budget = budget
        self.timeout = timeout
        self._current_method = current_method
        self._count_response_bytes = count_response_bytes
        self.requests = 0

    def _check_fatal(self) -> None:
        if self._budget.fatal_error is not None:
            raise self._budget.fatal_error
        rem = self._budget.remaining()
        if rem is not None and rem <= 0:
            raise self._budget.fail(self._budget.budget_error())

    def _check_modern_envelope(self, method: str, result: Mapping[str, Any]) -> None:
        if self.info.modern:
            _validate_cacheable_envelope(method, result)

    async def _send(
        self, method: str, request: Any, *, name_header: Optional[str] = None
    ) -> Dict[str, Any]:
        self._check_fatal()
        self._current_method[0] = method
        self._budget.last_http_status = None
        self.requests += 1
        metadata = None
        if name_header is not None and self.info.modern:
            try:
                encoded = self._sdk.encode_header_value(name_header)
            except UnicodeEncodeError as exc:
                raise McpError("request name is not valid Unicode") from exc
            metadata = self._sdk.ClientMessageMetadata(headers={self._sdk.MCP_NAME_HEADER: encoded})
        try:
            raw = await self._session.send_request(
                request,
                self._sdk.dict_adapter,
                request_read_timeout_seconds=self.timeout,
                metadata=metadata,
            )
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            raise _translate_error(
                exc, self._sdk, self._budget, method=method, timeout=self.timeout
            ) from exc
        if self._budget.fatal_error is not None:
            raise self._budget.fatal_error
        if not isinstance(raw, dict):
            raise McpError(f"{method} response result is not an object")
        if self._count_response_bytes:
            self._budget.charge(len(json.dumps(raw, ensure_ascii=False).encode("utf-8", "replace")))
        return raw

    async def iter_skills(self, *, max_pages: int = 1000) -> AsyncIterator[Any]:
        """Yield entries from ``skills/list``, fetching pages on demand."""
        cursor: Optional[str] = None
        for _ in range(max_pages):
            params = {"cursor": cursor} if cursor is not None else {}
            result = await self._send("skills/list", self._sdk.SkillsListRequest(params=params))
            self._check_modern_envelope("skills/list", result)
            skills = result.get("skills")
            if not isinstance(skills, list):
                raise McpError("skills/list result has no 'skills' array")
            for entry in skills:
                yield entry
            next_cursor = result.get("nextCursor")
            if next_cursor is None or next_cursor == "":
                return
            if not isinstance(next_cursor, str):
                raise McpError("skills/list returned a nextCursor that is not a string")
            cursor = next_cursor
        raise McpError(f"skills/list did not finish within {max_pages} pages")

    async def read_resource(self, uri: str) -> bytes:
        """Return the raw bytes ``resources/read`` provides for *uri*."""
        result = await self._send(
            "resources/read",
            self._sdk.ReadResourceRawRequest(params={"uri": uri}),
            name_header=uri,
        )
        self._check_modern_envelope("resources/read", result)
        contents = result.get("contents")
        if not isinstance(contents, list) or not contents:
            raise McpError("resources/read returned no contents")
        match = next((c for c in contents if isinstance(c, Mapping) and c.get("uri") == uri), None)
        if match is None:
            if any(isinstance(c, Mapping) and "uri" in c for c in contents):
                raise McpError("resources/read returned contents for a different URI")
            raise McpError("resources/read returned contents without a matching URI")
        text = match.get("text")
        if isinstance(text, str):
            try:
                return text.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise McpError("resources/read returned text that is not valid Unicode") from exc
        blob = match.get("blob")
        if isinstance(blob, str):
            try:
                return base64.b64decode(blob, validate=True)
            except ValueError as exc:
                raise McpError("resources/read returned invalid base64") from exc
        raise McpError("resources/read contents carry neither text nor blob")

    async def read_directory(
        self, uri: str, *, max_pages: int = 100, max_entries: int = 1024
    ) -> Tuple[List[Mapping[str, Any]], bool]:
        """Children of a directory resource (``directoryRead`` servers)."""
        children: List[Mapping[str, Any]] = []
        cursor: Optional[str] = None
        for _ in range(max_pages):
            params: Dict[str, Any] = {"uri": uri}
            if cursor is not None:
                params["cursor"] = cursor
            result = await self._send(
                "resources/directory/read",
                self._sdk.DirectoryReadRequest(params=params),
                name_header=uri,
            )
            self._check_modern_envelope("resources/directory/read", result)
            resources = result.get("resources")
            if not isinstance(resources, list):
                raise McpError("resources/directory/read result has no 'resources' array")
            for item in resources:
                if len(children) >= max_entries:
                    return children, False
                if not isinstance(item, Mapping):
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


@asynccontextmanager
async def open_mcp_session(
    *,
    kind: str,
    url: Optional[str] = None,
    headers: Optional[Mapping[str, str]] = None,
    command: Optional[List[str]] = None,
    env: Optional[Dict[str, str]] = None,
    cwd: Optional[Path] = None,
    timeout: float = 30.0,
    max_bytes: Optional[int] = None,
) -> AsyncIterator[McpSession]:
    """Connect to an MCP server over Streamable HTTP or stdio via the MCP SDK."""
    from . import __version__

    sdk = _load_sdk()
    budget = _Budget(max_bytes)
    current_method = ["server/discover"]
    stack = AsyncExitStack()
    await stack.__aenter__()
    session_exc: Optional[BaseException] = None
    try:
        try:
            if kind == "http":
                if not url:
                    raise McpError("missing server URL")
                http_client = _build_http_client(
                    sdk, url, headers or {}, timeout, budget, current_method
                )
                await stack.enter_async_context(http_client)
                max_sse = min(MAX_MESSAGE_BYTES, max_bytes) if max_bytes else MAX_MESSAGE_BYTES
                transport = sdk.streamable_http_client(
                    url, http_client=http_client, max_sse_event_size=max_sse
                )
            elif kind == "stdio":
                if not command:
                    raise McpError("empty server command")
                devnull = stack.enter_context(open(os.devnull, "w", encoding="utf-8"))
                params = sdk.StdioServerParameters(
                    command=command[0],
                    args=command[1:],
                    env=dict(os.environ) if env is None else env,
                    cwd=cwd,
                )
                transport = sdk.stdio_client(params, errlog=devnull)
            else:
                raise McpError(f"unsupported transport {kind!r}")

            client = sdk.Client(
                transport,
                mode="auto",
                extensions=[sdk.advertise(EXTENSION_ID)],
                client_info=sdk.types.Implementation(name="skillsaw", version=__version__),
                read_timeout_seconds=timeout,
                cache=None,
            )
            await stack.enter_async_context(client)
            sdk_session = client.session
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            if kind == "stdio":
                for leaf in _iter_leaf_exceptions(exc):
                    if isinstance(leaf, ValueError):
                        raise McpError(
                            "could not start the server: its command, arguments, environment or "
                            "working directory hold a character the system refuses"
                        ) from exc
                    if isinstance(leaf, OSError):
                        prog = command[0] if command else "server"
                        raise McpError(
                            f"could not start {prog!r}: {leaf.strerror or leaf}"
                        ) from exc
            raise _translate_error(
                exc, sdk, budget, method=current_method[0], timeout=timeout
            ) from exc

        if budget.fatal_error is not None:
            raise budget.fatal_error
        info = _server_info_from_session(sdk_session)
        session = McpSession(
            sdk=sdk,
            session=sdk_session,
            info=info,
            budget=budget,
            timeout=timeout,
            current_method=current_method,
            count_response_bytes=(kind == "stdio"),
        )
        yield session
    except BaseException as exc:
        session_exc = exc
        raise
    finally:
        try:
            await stack.aclose()
        except BaseException as close_exc:
            if session_exc is None and not isinstance(close_exc, (KeyboardInterrupt, SystemExit)):
                raise _translate_error(
                    close_exc, sdk, budget, method=current_method[0], timeout=timeout
                ) from close_exc

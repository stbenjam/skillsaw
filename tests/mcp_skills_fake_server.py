"""A small MCP server that publishes a skills directory, for tests.

It implements just what ``skillsaw lint --mcp-server`` exercises —
``server/discover`` (modern era), ``initialize`` (legacy era), ``skills/list``
with pagination, ``skills/get``, ``resources/read`` and
``resources/directory/read`` — over stdio or Streamable HTTP, and can be told
to misbehave so the lint has something to catch.

Run as a script for stdio: ``python mcp_skills_fake_server.py SKILLS_DIR
[--legacy] [--tamper SUFFIX] [--lie-frontmatter NAME] [--dynamic NAME]``.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from skillsaw.utils import _SAFE_LOADER

EXTENSION = "io.modelcontextprotocol/skills"
MODERN = "2026-07-28"
PAGE_SIZE = 2


@dataclass
class Options:
    legacy: bool = False
    tamper: List[str] = field(default_factory=list)
    lie_frontmatter: List[str] = field(default_factory=list)
    dynamic: List[str] = field(default_factory=list)
    sse: bool = False
    no_extension: bool = False
    # Raw entries appended to skills/list, and the bytes behind their URIs —
    # for entries no well-behaved directory would produce.
    extra_entries: List[Dict[str, Any]] = field(default_factory=list)
    extra_files: Dict[str, bytes] = field(default_factory=dict)
    # skills/list never ends: every page carries a cursor to another.
    endless_list: bool = False
    # Every directory read lists ten new subdirectories, one repeated, and a
    # grandchild posing as a direct child.
    fan_out_directories: bool = False
    # HTTP only: send headers and a short body, then stall on the rest.
    stall_body_seconds: float = 0.0
    # HTTP only: answer the first N requests, and every read of these URIs,
    # with 429 Too Many Requests.
    busy_first: int = 0
    busy_uris: List[str] = field(default_factory=list)
    # HTTP only: fail every resources/read with a 500 and this many bytes.
    error_body_bytes: int = 0
    # HTTP only: refuse every notification with a 400 and this many bytes.
    notification_error_bytes: int = 0
    # resources/read text served for a URI as-is, e.g. with a lone surrogate.
    text_overrides: Dict[str, str] = field(default_factory=dict)
    # HTTP only: answer 401, as an OAuth-protected server does, unless the
    # request carries "Authorization: Bearer <this token>".
    require_token: str = ""
    # skills/list in reverse order, so a nested skill comes before its parent.
    reverse_listing: bool = False
    # resources/read of a key answers with the value's URI and contents.
    misattributed_reads: Dict[str, str] = field(default_factory=dict)
    # Every resources/read waits this long before it answers.
    stall_reads_seconds: float = 0.0
    # skills/list pages carry their cursor as a number, not a string.
    malformed_cursor: bool = False
    # Every directory listing also carries this malformed entry.
    malformed_directory_entry: Any = None


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _frontmatter(text: str) -> Dict[str, Any]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    data = yaml.load(text[4:end], Loader=_SAFE_LOADER) if end != -1 else None
    return data if isinstance(data, dict) else {}


class Catalog:
    def __init__(self, root: Path, options: Options):
        self.options = options
        self.files: Dict[str, bytes] = {}
        self.entries: List[Dict[str, Any]] = []
        self.dirs: Dict[str, List[str]] = {}
        for skill_md in sorted(root.rglob("SKILL.md")):
            skill_dir = skill_md.parent
            rel = skill_dir.relative_to(root).as_posix()
            base = f"skill://{rel}"
            resources = []
            for path in sorted(p for p in skill_dir.rglob("*") if p.is_file()):
                uri = f"{base}/{path.relative_to(skill_dir).as_posix()}"
                data = path.read_bytes()
                self.files[uri] = data
                resources.append({"uri": uri, "digest": _digest(data), "size": len(data)})
                self._index(uri, base)
            frontmatter = _frontmatter(skill_md.read_text(encoding="utf-8"))
            frontmatter = json.loads(json.dumps(frontmatter, default=str))
            if skill_dir.name in options.lie_frontmatter:
                frontmatter = {**frontmatter, "description": "Something else entirely"}
            entry: Dict[str, Any] = {"uri": f"{base}/SKILL.md", "frontmatter": frontmatter}
            entry["resources"] = "dynamic" if skill_dir.name in options.dynamic else resources
            self.entries.append(entry)
        if options.reverse_listing:
            self.entries.reverse()
        self.entries.extend(options.extra_entries)
        self.files.update(options.extra_files)
        for uri in list(self.files):
            for suffix in options.tamper:
                if uri.endswith(suffix):
                    self.files[uri] = self.files[uri] + b"\n<!-- injected after listing -->\n"

    def _index(self, uri: str, base: str) -> None:
        parent = uri.rsplit("/", 1)[0]
        child = uri
        while True:
            self.dirs.setdefault(parent, [])
            if child not in self.dirs[parent]:
                self.dirs[parent].append(child)
            if parent == base or "/" not in parent[len("skill://") :]:
                break
            child, parent = parent, parent.rsplit("/", 1)[0]


class Server:
    def __init__(self, catalog: Catalog):
        self.catalog = catalog
        self.options = catalog.options
        self.initialized = False
        self.calls: List[str] = []  # methods of the requests received, in order
        self.busy_remaining = self.options.busy_first

    def capabilities(self) -> Dict[str, Any]:
        caps: Dict[str, Any] = {"resources": {}}
        if not self.options.no_extension:
            caps["extensions"] = {EXTENSION: {"directoryRead": True}}
        return caps

    def handle(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        method = message.get("method")
        if "id" not in message:
            if method == "notifications/initialized":
                self.initialized = True
            return None
        params = message.get("params") or {}
        self.calls.append(method)
        try:
            result = self.dispatch(method, params)
        except _RpcError as exc:
            return {"jsonrpc": "2.0", "id": message["id"], "error": exc.payload()}
        return {"jsonrpc": "2.0", "id": message["id"], "result": result}

    def dispatch(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if method == "server/discover":
            if self.options.legacy:
                raise _RpcError(-32601, "Method not found")
            return {
                "resultType": "complete",
                "supportedVersions": [MODERN],
                "capabilities": self.capabilities(),
                "_meta": {"io.modelcontextprotocol/serverInfo": {"name": "fake", "version": "1"}},
                "ttlMs": 0,
                "cacheScope": "private",
            }
        if method == "initialize":
            return {
                "protocolVersion": "2025-11-25",
                "capabilities": self.capabilities(),
                "serverInfo": {"name": "fake-legacy", "version": "1"},
            }
        if self.options.legacy and not self.initialized:
            raise _RpcError(-32002, "Server not initialized")
        if not self.options.legacy:
            meta = params.get("_meta") or {}
            if meta.get("io.modelcontextprotocol/protocolVersion") != MODERN:
                raise _RpcError(-32022, "Unsupported protocol version", {"supported": [MODERN]})
        if method == "skills/list" and self.options.endless_list:
            start = int(params.get("cursor") or 0)
            page = [
                {
                    "uri": f"skill://generated-{n}/SKILL.md",
                    "frontmatter": {"name": f"generated-{n}", "description": "Generated."},
                    "resources": "dynamic",
                }
                for n in range(start, start + PAGE_SIZE)
            ]
            return {
                "resultType": "complete",
                "skills": page,
                "nextCursor": str(start + PAGE_SIZE),
                "ttlMs": 0,
                "cacheScope": "private",
            }
        if method == "skills/list":
            start = int(params.get("cursor") or 0)
            page = self.catalog.entries[start : start + PAGE_SIZE]
            result: Dict[str, Any] = {
                "resultType": "complete",
                "skills": page,
                "ttlMs": 0,
                "cacheScope": "private",
            }
            if start + PAGE_SIZE < len(self.catalog.entries):
                cursor = start + PAGE_SIZE
                result["nextCursor"] = cursor if self.options.malformed_cursor else str(cursor)
            return result
        if method == "skills/get":
            for entry in self.catalog.entries:
                if entry["uri"] == params.get("uri"):
                    return {
                        "resultType": "complete",
                        "skill": entry,
                        "ttlMs": 0,
                        "cacheScope": "private",
                    }
            raise _RpcError(-32602, "No such skill")
        if method == "resources/read" and params.get("uri") in self.options.text_overrides:
            uri = params["uri"]
            return {
                "resultType": "complete",
                "contents": [{"uri": uri, "text": self.options.text_overrides[uri]}],
                "ttlMs": 0,
                "cacheScope": "private",
            }
        if method == "resources/read":
            time.sleep(self.options.stall_reads_seconds)
            uri = self.options.misattributed_reads.get(params.get("uri"), params.get("uri"))
            data = self.catalog.files.get(uri)
            if data is None:
                raise _RpcError(-32602, "No such resource")
            try:
                content: Dict[str, Any] = {"uri": uri, "text": data.decode("utf-8")}
            except UnicodeDecodeError:
                content = {"uri": uri, "blob": base64.b64encode(data).decode("ascii")}
            return {
                "resultType": "complete",
                "contents": [content],
                "ttlMs": 0,
                "cacheScope": "private",
            }
        if method == "resources/directory/read" and self.options.fan_out_directories:
            uri = params.get("uri")
            children = [
                {"uri": f"{uri}/d{n}", "name": f"d{n}", "mimeType": "inode/directory"}
                for n in range(10)
            ]
            children.append(dict(children[0]))
            children.append(
                {"uri": f"{uri}/d0/deeper", "name": "deeper", "mimeType": "inode/directory"}
            )
            return {
                "resultType": "complete",
                "resources": children,
                "ttlMs": 0,
                "cacheScope": "private",
            }
        if method == "resources/directory/read":
            uri = params.get("uri")
            if uri not in self.catalog.dirs:
                raise _RpcError(-32602, "Not a directory")
            children = [
                (
                    {"uri": c, "name": c.rsplit("/", 1)[1], "mimeType": "inode/directory"}
                    if c in self.catalog.dirs
                    else {"uri": c, "name": c.rsplit("/", 1)[1], "mimeType": "text/markdown"}
                )
                for c in self.catalog.dirs[uri]
            ]
            if self.options.malformed_directory_entry is not None:
                children.append(self.options.malformed_directory_entry)
            return {
                "resultType": "complete",
                "resources": children,
                "ttlMs": 0,
                "cacheScope": "private",
            }
        raise _RpcError(-32601, "Method not found")


class _RpcError(Exception):
    def __init__(self, code: int, message: str, data: Any = None):
        super().__init__(message)
        self.code, self.message, self.data = code, message, data

    def payload(self) -> Dict[str, Any]:
        error: Dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            error["data"] = self.data
        return error


def serve_stdio(server: Server) -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        response = server.handle(json.loads(line))
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


def start_http(server: Server) -> ThreadingHTTPServer:
    """Serve on an ephemeral localhost port in a daemon thread."""
    sessions = set()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # keep test output quiet
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            message = json.loads(body)
            token = server.options.require_token
            if token and self.headers.get("Authorization") != f"Bearer {token}":
                server.calls.append(message.get("method"))
                self.send_response(401)
                self.send_header(
                    "WWW-Authenticate",
                    'Bearer resource_metadata="http://127.0.0.1/.well-known/oauth-protected-resource"',
                )
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if server.options.notification_error_bytes and "id" not in message:
                server.calls.append(message.get("method"))
                payload = b"x" * server.options.notification_error_bytes
                self.send_response(400)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            if server.options.error_body_bytes and message.get("method") == "resources/read":
                server.calls.append("resources/read")
                payload = b"x" * server.options.error_body_bytes
                self.send_response(500)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            busy_uri = (message.get("params") or {}).get("uri") in server.options.busy_uris
            if server.busy_remaining > 0 or busy_uri:
                if not busy_uri:
                    server.busy_remaining -= 1
                self.send_response(429)
                self.send_header("Retry-After", "0")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            headers = {}
            if server.options.legacy:
                if message.get("method") == "server/discover":
                    self.send_response(404)
                    self.end_headers()
                    return
                if message.get("method") == "initialize":
                    sessions.add("session-1")
                    headers["Mcp-Session-Id"] = "session-1"
                elif self.headers.get("Mcp-Session-Id") not in sessions:
                    self.send_response(400)
                    self.end_headers()
                    return
            elif self.headers.get("Mcp-Method") != message.get("method"):
                self._json(
                    400,
                    {
                        "jsonrpc": "2.0",
                        "id": message.get("id"),
                        "error": {"code": -32020, "message": "HeaderMismatch"},
                    },
                )
                return
            response = server.handle(message)
            if server.options.stall_body_seconds and response is not None:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", "100000")
                self.end_headers()
                self.wfile.write(b'{"jsonrpc": "2.0", ')
                self.wfile.flush()
                time.sleep(server.options.stall_body_seconds)
                return
            if response is None:
                self.send_response(202)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.end_headers()
                return
            status = 400 if "error" in response and response["error"]["code"] == -32022 else 200
            if server.options.sse and status == 200:
                payload = (
                    'event: message\ndata: {"jsonrpc":"2.0","method":"notifications/progress",'
                    '"params":{}}\n\n' + "event: message\ndata: " + json.dumps(response) + "\n\n"
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
            else:
                payload = json.dumps(response).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _json(self, status, obj):
            payload = json.dumps(obj).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def main(argv=None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("skills_dir", type=Path)
    parser.add_argument("--legacy", action="store_true")
    parser.add_argument("--tamper", action="append", default=[])
    parser.add_argument("--lie-frontmatter", action="append", default=[])
    parser.add_argument("--dynamic", action="append", default=[])
    args = parser.parse_args(argv)
    options = Options(
        legacy=args.legacy,
        tamper=args.tamper,
        lie_frontmatter=args.lie_frontmatter,
        dynamic=args.dynamic,
    )
    serve_stdio(Server(Catalog(args.skills_dir, options)))


if __name__ == "__main__":
    main()

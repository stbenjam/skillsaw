"""Tests for ``content-broken-external-reference``.

**No test in this file — or anywhere in the suite — may reach the real
internet.** Every request goes to a local ``http.server`` bound to
127.0.0.1 on an ephemeral port, and the server records every hit so the
tests can assert on what was requested *and* on what was not. The
default-configuration test proves the stronger property: with the rule
left at its default, a lint run cannot open a socket at all.

The markdown lives in ``tests/fixtures/content/external-links*`` per the
repository's fixture-first testing rules; only the port — unknowable
until the server binds — is substituted into the copied fixture.
"""

import shutil
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import List, Tuple

import pytest

from skillsaw.config import LinterConfig
from skillsaw.context import RepositoryContext
from skillsaw.linter import Linter
from skillsaw.rule import Severity
from skillsaw.rules.builtin.content import ContentBrokenExternalReferenceRule

from .test_integration import FIXTURES, run_lint

RULE_ID = "content-broken-external-reference"

# How long ``/slow`` and ``/slow-index`` stall before answering. Long
# enough that a sub-second timeout or budget always expires first, short
# enough that a hung test still finishes.
_SLOW_SECONDS = 3.0


# ── Local scripted HTTP server ───────────────────────────────────


class _ScriptedHandler(BaseHTTPRequestHandler):
    """Answers a fixed route table and records every request it sees.

    HTTP/1.0, so each response closes the connection: the rule reads
    status and headers and never the body, and a half-read keep-alive
    connection would otherwise leave the handler thread writing into a
    closed socket.
    """

    protocol_version = "HTTP/1.0"

    def log_message(self, *args):  # noqa: D102 - silence the default stderr log
        pass

    def _respond(self, status: int, location: str = None, body: bytes = b""):
        self.send_response(status)
        if location is not None:
            self.send_header("Location", location)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)

    def _handle(self, method: str):
        path = self.path
        self.server.hits.append((method, path))
        if path == "/ok":
            self._respond(200, body=b"ok")
        elif path == "/missing":
            self._respond(404, body=b"not found")
        elif path == "/gone":
            self._respond(410, body=b"gone")
        elif path == "/forbidden":
            self._respond(403, body=b"forbidden")
        elif path == "/rate-limited":
            self._respond(429, body=b"slow down")
        elif path == "/server-error":
            self._respond(500, body=b"boom")
        elif path == "/redirect-ok":
            self._respond(302, location="/relocated-ok")
        elif path == "/relocated-ok":
            self._respond(200, body=b"ok")
        elif path == "/redirect-missing":
            # A distinct target, so the de-duplication test can count
            # requests to /missing without redirect traffic landing there.
            self._respond(302, location="/relocated")
        elif path == "/relocated":
            self._respond(404, body=b"not found")
        elif path == "/redirect-loop":
            self._respond(302, location="/redirect-loop")
        elif path == "/redirect-ftp":
            self._respond(302, location="ftp://127.0.0.1/pub/file")
        elif path == "/head-405":
            # Rejects HEAD outright; the GET retry finds it is gone.
            self._respond(405 if method == "HEAD" else 404, body=b"")
        elif path.startswith("/slow"):
            # Never answers within any timeout the tests configure.
            _stalled = threading.Event()
            _stalled.wait(_SLOW_SECONDS)
            self._respond(200, body=b"eventually")
        else:
            self._respond(404, body=b"no route")

    def do_HEAD(self):  # noqa: N802 - BaseHTTPRequestHandler naming
        self._handle("HEAD")

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler naming
        self._handle("GET")


class _QuietServer(ThreadingHTTPServer):
    """A server that does not print when a client hangs up early.

    The timeout tests deliberately abandon a request mid-flight, and the
    default handler would dump a BrokenPipeError traceback per test.
    """

    def handle_error(self, request, client_address):
        pass


class _LocalServer:
    """A scripted HTTP server on an ephemeral 127.0.0.1 port."""

    def __init__(self):
        self._httpd = _QuietServer(("127.0.0.1", 0), _ScriptedHandler)
        self._httpd.daemon_threads = True
        self._httpd.hits: List[Tuple[str, str]] = []
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    @property
    def port(self) -> int:
        return self._httpd.server_address[1]

    @property
    def hits(self) -> List[Tuple[str, str]]:
        return self._httpd.hits

    def paths(self) -> List[str]:
        return [path for _method, path in self.hits]

    def reset(self):
        self._httpd.hits.clear()

    def close(self):
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)


@pytest.fixture(scope="module")
def _module_server():
    server = _LocalServer()
    yield server
    server.close()


@pytest.fixture
def server(_module_server):
    _module_server.reset()
    return _module_server


@pytest.fixture(autouse=True)
def _no_proxy(monkeypatch):
    """Never route a test request through an ambient proxy.

    ``urllib`` reads the proxy environment, so a developer machine or CI
    runner with ``http_proxy`` set would send these localhost requests
    somewhere else entirely — off the loopback interface, which is
    exactly what this file promises never to do.
    """
    for var in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("no_proxy", "*")
    monkeypatch.setenv("NO_PROXY", "*")


def _materialize(fixture: str, tmp_path: Path, port: int, keep_config: bool = True) -> Path:
    """Copy a fixture and substitute the server's port into its markdown.

    ``keep_config=False`` drops the fixture's opt-in ``.skillsaw.yaml``,
    leaving a repository that a lint run sees exactly as an unconfigured
    user's would — which is what the hermeticity tests need.
    """
    repo = tmp_path / fixture.replace("/", "_")
    shutil.copytree(FIXTURES / fixture, repo)
    for md in repo.rglob("*.md"):
        text = md.read_text(encoding="utf-8")
        if "__PORT__" in text:
            md.write_text(text.replace("__PORT__", str(port)), encoding="utf-8")
    if not keep_config:
        (repo / ".skillsaw.yaml").unlink()
    return repo


def _closed_port() -> int:
    """An ephemeral port with nothing listening on it."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _run_rule(repo: Path, config: dict = None):
    rule = ContentBrokenExternalReferenceRule({"enabled": True, **(config or {})})
    return rule.check(RepositoryContext(repo))


def _messages(violations):
    return [v.message for v in violations]


# ── Rule metadata ────────────────────────────────────────────────


class TestMetadata:
    def test_rule_identity(self):
        rule = ContentBrokenExternalReferenceRule()
        assert rule.rule_id == RULE_ID
        assert rule.default_severity() == Severity.WARNING
        assert rule.since == "0.20.0"

    def test_rule_is_opt_in(self):
        """Never ``auto``: nothing may start making requests on its own."""
        assert ContentBrokenExternalReferenceRule.default_enabled is False

    def test_rule_has_no_autofix(self):
        """There is no mechanical fix for a dead URL."""
        assert ContentBrokenExternalReferenceRule().supports_autofix is False

    def test_disabled_in_generated_default_config(self):
        assert LinterConfig.default().rules[RULE_ID]["enabled"] is False


# ── URL extraction (no I/O) ──────────────────────────────────────


class TestUrlSelection:
    @pytest.mark.parametrize(
        "href,expected",
        [
            ("https://example.com/a", "https://example.com/a"),
            ("http://example.com/a?q=1#frag", "http://example.com/a?q=1"),
            ("HTTPS://Example.com/a", "https://Example.com/a"),
            # Out of scope: not http(s), no host, or carrying credentials.
            ("mailto:someone@example.com", None),
            ("ftp://example.com/pub", None),
            ("app://connector/id", None),
            ("./docs/guide.md", None),
            ("#anchor", None),
            ("https:///nohost", None),
            ("https://user:token@example.com/a", None),
        ],
    )
    def test_request_url(self, href, expected):
        assert ContentBrokenExternalReferenceRule._request_url(href) == expected

    @pytest.mark.parametrize(
        "url,patterns,expected",
        [
            ("https://internal.example.com/x", ["https://internal.example.com/"], True),
            ("https://other.example.com/x", ["https://internal.example.com/"], False),
            ("https://a.staging.example.net/x", ["https://*.staging.example.net/*"], True),
            ("https://a.prod.example.net/x", ["https://*.staging.example.net/*"], False),
            ("https://example.com/x", [], False),
            ("https://example.com/x", [None, "", "https://example.com"], True),
        ],
    )
    def test_ignore_matching(self, url, patterns, expected):
        assert ContentBrokenExternalReferenceRule._is_ignored(url, patterns) is expected


# ── Detection against the local server ───────────────────────────


class TestAgainstLocalServer:
    def test_only_404_and_410_are_reported(self, tmp_path, server):
        repo = _materialize("content/external-links", tmp_path, server.port)

        violations = _run_rule(repo)

        assert [v.rule_id for v in violations] == [RULE_ID] * len(violations)
        broken = sorted(
            v.message.split("](")[1].split(")")[0].rsplit("/", 1)[1] for v in violations
        )
        # /missing appears three times across two files; /head-405 is only
        # discovered broken by the GET retry; /redirect-missing lands on a
        # 404 after one hop.
        assert broken == [
            "gone",
            "head-405",
            "missing",
            "missing",
            "missing",
            "redirect-missing",
        ]

    def test_bot_walls_and_flakiness_are_not_violations(self, tmp_path, server):
        repo = _materialize("content/external-links", tmp_path, server.port)

        violations = _run_rule(repo)

        joined = "\n".join(_messages(violations))
        for never_flagged in (
            "/forbidden",  # 403 bot wall
            "/rate-limited",  # 429 rate limit
            "/server-error",  # 5xx origin error
            "/redirect-loop",  # exceeds the hop cap
            "/redirect-ok",  # 302 -> 200
            "/ok",  # 200
        ):
            assert never_flagged not in joined

    def test_violation_carries_file_and_line(self, tmp_path, server):
        repo = _materialize("content/external-links", tmp_path, server.port)

        violations = _run_rule(repo)

        located = {(v.file_path.name, v.file_line) for v in violations if "/missing" in v.message}
        claude_md = (repo / "CLAUDE.md").read_text().splitlines()
        for name, line in located:
            assert line is not None
            if name == "CLAUDE.md":
                assert "/missing" in claude_md[line - 1]
        assert {name for name, _ in located} == {"CLAUDE.md", "SKILL.md"}

    def test_each_url_is_requested_once(self, tmp_path, server):
        """Three occurrences of one URL cost one request, not three."""
        repo = _materialize("content/external-links", tmp_path, server.port)

        _run_rule(repo)

        assert server.paths().count("/missing") == 1

    def test_head_first_then_get_only_when_head_is_rejected(self, tmp_path, server):
        repo = _materialize("content/external-links", tmp_path, server.port)

        _run_rule(repo)

        methods = {}
        for method, path in server.hits:
            methods.setdefault(path, []).append(method)
        # Every URL is probed with HEAD; only the 405 route earns a GET.
        assert methods["/ok"] == ["HEAD"]
        assert methods["/gone"] == ["HEAD"]
        assert methods["/head-405"] == ["HEAD", "GET"]

    def test_urls_in_code_fences_are_never_requested(self, tmp_path, server):
        repo = _materialize("content/external-links", tmp_path, server.port)

        violations = _run_rule(repo)

        assert "/definitely-not-requested" not in server.paths()
        assert "definitely-not-requested" not in "\n".join(_messages(violations))

    def test_autolinks_are_collected(self, tmp_path, server):
        """``<http://…>`` is a link in the AST and is probed like any other."""
        repo = _materialize("content/external-links", tmp_path, server.port)

        _run_rule(repo)

        assert "/rate-limited" in server.paths()

    def test_ignored_urls_are_never_requested(self, tmp_path, server):
        repo = _materialize("content/external-links", tmp_path, server.port)

        violations = _run_rule(
            repo,
            {"ignore": [f"http://127.0.0.1:{server.port}/missing", "*/gone"]},
        )

        assert "/missing" not in server.paths()
        assert "/gone" not in server.paths()
        joined = "\n".join(_messages(violations))
        assert "/missing" not in joined
        assert "/gone" not in joined

    def test_redirect_out_of_http_is_not_followed(self, server):
        """A 302 into ``ftp://`` ends the chain instead of changing protocol."""
        rule = ContentBrokenExternalReferenceRule({"enabled": True})

        status, checked = rule._probe(f"http://127.0.0.1:{server.port}/redirect-ftp", 5.0, None)

        assert checked is True
        assert status not in (404, 410)
        assert server.paths() == ["/redirect-ftp"]

    def test_result_is_deterministic(self, tmp_path, server):
        repo = _materialize("content/external-links", tmp_path, server.port)

        first = _messages(_run_rule(repo))
        second = _messages(_run_rule(repo))

        assert first == second


# ── Failure modes that must stay silent ──────────────────────────


class TestInconclusiveNetwork:
    def test_offline_produces_no_violations(self, tmp_path):
        """Connection refused says nothing about the link."""
        repo = _materialize("content/external-links", tmp_path, _closed_port())

        assert _run_rule(repo) == []

    def test_unresolvable_host_produces_no_violations(self, tmp_path, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "# Project\n\n"
            "Read the [design notes](https://host.invalid/notes.md) before "
            "changing the parser.\n",
            encoding="utf-8",
        )

        # .invalid is reserved by RFC 2606 and never resolves, so this
        # exercises DNS failure without leaving the machine.
        assert _run_rule(temp_dir) == []

    def test_timeout_produces_no_violations(self, tmp_path, server):
        repo = _materialize("content/external-links-slow", tmp_path, server.port)

        violations = _run_rule(repo, {"timeout": 0.5, "total-budget": 30, "concurrency": 2})

        assert violations == []

    def test_exhausted_budget_emits_one_info_notice(self, tmp_path, server):
        repo = _materialize("content/external-links-slow", tmp_path, server.port)

        # One worker, a one-second budget, two URLs that never answer: the
        # first burns the budget, the second is never requested.
        violations = _run_rule(repo, {"timeout": 5, "total-budget": 1, "concurrency": 1})

        assert len(violations) == 1
        notice = violations[0]
        assert notice.severity == Severity.INFO
        assert "1 external URL(s) unchecked" in notice.message
        assert "budget of 1s exhausted" in notice.message
        assert len(server.paths()) == 1

    def test_no_notice_when_nothing_was_skipped(self, tmp_path, server):
        repo = _materialize("content/external-links", tmp_path, server.port)

        violations = _run_rule(repo)

        assert not any("unchecked" in v.message for v in violations)


# ── The hermeticity guarantee ────────────────────────────────────


class TestDefaultRunIsOffline:
    def test_default_config_makes_no_requests(self, tmp_path, server):
        """A lint with no config never touches the server."""
        repo = _materialize("content/external-links", tmp_path, server.port, keep_config=False)

        result = run_lint(repo)

        assert result["out"] is not None
        assert RULE_ID not in {v["rule_id"] for v in result["out"]["violations"]}
        assert server.hits == []

    def test_default_run_cannot_open_a_socket(self, tmp_path, server, monkeypatch):
        """Stronger than counting hits: every rule runs with sockets bricked.

        If any rule in a default run ever tried to connect anywhere, this
        raises instead of quietly succeeding against a reachable host.
        """
        repo = _materialize("content/external-links", tmp_path, server.port, keep_config=False)

        def _refuse(*args, **kwargs):
            raise AssertionError("a default lint run must not open a socket")

        monkeypatch.setattr(socket.socket, "connect", _refuse)
        monkeypatch.setattr(socket.socket, "connect_ex", _refuse)

        Linter(RepositoryContext(repo), LinterConfig.default()).run()

        assert server.hits == []

    def test_enabling_the_rule_is_what_turns_the_network_on(self, tmp_path, server):
        repo = _materialize("content/external-links", tmp_path, server.port)

        result = run_lint(repo, config=repo / ".skillsaw.yaml")

        fired = [v for v in result["out"]["violations"] if v["rule_id"] == RULE_ID]
        assert len(fired) == 6
        assert server.hits != []
        assert {v["file_path"] for v in fired} == {
            "CLAUDE.md",
            "skills/release-checklist/SKILL.md",
        }
        assert all(v["line"] for v in fired)

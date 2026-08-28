"""Tests for ``content-broken-external-reference``.

**No test in this file — or anywhere in the suite — may reach the real
internet.** Every request goes to a local ``http.server`` bound to
127.0.0.1 on an ephemeral port, and the server records every hit so the
tests can assert on what was requested *and* on what was not. The
default-configuration test proves the stronger property: with the rule
left at its default, a lint run cannot open a socket at all.

The markdown lives in ``tests/fixtures/content/external-links`` and
``tests/fixtures/content/external-links-slow``. Only the port —
unknowable until the server binds — is substituted into the copied
fixture.
"""

import email
import http.client
import ipaddress
import shutil
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import List, Tuple
from urllib.parse import unquote, urlparse

import pytest

from skillsaw.config import LinterConfig
from skillsaw.context import RepositoryContext
from skillsaw.linter import Linter
from skillsaw.rule import Severity
from skillsaw.rules.builtin.content import ContentBrokenExternalReferenceRule
from skillsaw.rules.builtin.content.broken_external_reference import (
    _BoundedRedirectHandler,
    _EmptyBody,
    _MAX_IGNORE_PATTERN_LENGTH,
    _MAX_URL_LENGTH,
)

from .cli_runner import run_cli
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

    # path -> (status, Location or None). Redirect targets are distinct
    # from the plain routes so the de-duplication test can count requests
    # to /missing without redirect traffic landing there.
    ROUTES = {
        "/ok": (200, None),
        "/sla": (200, None),
        "/badge.svg": (200, None),
        "/missing": (404, None),
        "/gone": (410, None),
        "/forbidden": (403, None),
        "/rate-limited": (429, None),
        "/server-error": (500, None),
        "/redirect-ok": (302, "/relocated-ok"),
        "/relocated-ok": (200, None),
        "/redirect-missing": (302, "/relocated"),
        "/relocated": (404, None),
        "/redirect-loop": (302, "/redirect-loop"),
        "/redirect-ftp": (302, "ftp://127.0.0.1/pub/file"),
        # An unclosed IPv6 literal: urllib parses this header itself,
        # before the hop is ever offered to the admission gate.
        "/redirect-malformed": (302, "http://[::1/x"),
    }

    # path -> (status to HEAD, status to GET). Every route where the two
    # methods disagree, which is what the GET retry and the GET
    # confirmation exist for.
    SPLIT_ROUTES = {
        "/head-405": (405, 404),  # refuses HEAD; the retry finds it gone
        "/head-501": (501, 404),  # the other spelling of that refusal
        "/head-404-get-200": (404, 200),  # nvlpubs.nist.gov's shape
        "/head-410-get-200": (410, 200),  # the same, spelled 410
    }

    def _handle(self, method: str):
        path = self.path
        self.server.hits.append((method, path))
        if path in self.ROUTES:
            status, location = self.ROUTES[path]
            self._respond(status, location=location, body=b"body")
        elif path in self.SPLIT_ROUTES:
            to_head, to_get = self.SPLIT_ROUTES[path]
            self._respond(to_head if method == "HEAD" else to_get, body=b"body")
        elif path.startswith("/hop/"):
            # A chain of DISTINCT hops, so it trips the hop cap rather
            # than urllib's untouched same-URL max_repeats.
            step = int(path.rsplit("/", 1)[1])
            if step <= 1:
                self._respond(404, body=b"end of chain")
            else:
                self._respond(302, location=f"/hop/{step - 1}")
        elif path.startswith("/slow"):
            # Never answers within any timeout the tests configure.
            threading.Event().wait(_SLOW_SECONDS)
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
    Only those are swallowed: a typo in ``ROUTES`` must still show its
    traceback rather than becoming a quiet 404 that reads as green.
    """

    _EXPECTED = (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], self._EXPECTED):
            return
        super().handle_error(request, client_address)


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
def _neutral_network_environment(monkeypatch):
    """Neither an ambient proxy nor an ambient operator decision.

    The proxy half: ``urllib`` reads the proxy environment, so a
    developer machine or CI runner with ``http_proxy`` set would send
    these localhost requests somewhere else entirely — off the loopback
    interface, which is exactly what this file promises never to do.

    The operator half: ``SKILLSAW_NO_NETWORK`` is a variable the docs
    tell people to export CI-wide, and ``conftest.py`` copies a
    developer ``.env`` into ``os.environ``. Either would silently gate
    every test here.
    """
    for var in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.delenv(var, raising=False)
    for var in ("SKILLSAW_NO_NETWORK", "SKILLSAW_ALLOW_PRIVATE_HOSTS"):
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


@pytest.fixture
def closed_port():
    """An ephemeral port bound but never listened on — always refused.

    Binding and immediately closing would free the port, and ``make
    test`` runs xdist workers that bind ``("127.0.0.1", 0)`` at the same
    time: a sibling could take it and answer. Holding the socket for the
    test's lifetime keeps ECONNREFUSED deterministic.
    """
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    try:
        yield sock.getsockname()[1]
    finally:
        sock.close()


def _run_rule(repo: Path, config: dict = None, *, allow_private_hosts: bool = True):
    # The loopback server is only reachable because the *operator* opted
    # in, which is a constructor argument and never a config key:
    # `.skillsaw.yaml` is the untrusted input that control defends
    # against. Tests exercising the refusal pass allow_private_hosts=False.
    settings = {"enabled": True}
    settings.update(config or {})
    rule = ContentBrokenExternalReferenceRule(settings, allow_private_hosts=allow_private_hosts)
    return rule.check(RepositoryContext(repo))


def _messages(violations):
    return [v.message for v in violations]


def _methods_by_path(server):
    """``{path: [method, ...]}`` in request order."""
    methods = {}
    for method, path in server.hits:
        methods.setdefault(path, []).append(method)
    return methods


# ── Rule metadata ────────────────────────────────────────────────


class TestMetadata:
    def test_rule_identity_and_opt_in_defaults(self):
        """`default_enabled` is never ``auto``: nothing starts requesting
        on its own, and there is no mechanical fix for a dead URL."""
        rule = ContentBrokenExternalReferenceRule()

        assert rule.rule_id == RULE_ID
        assert rule.default_severity() == Severity.WARNING
        assert rule.since == "0.20.0"
        assert rule.supports_autofix is False
        assert ContentBrokenExternalReferenceRule.default_enabled is False
        assert LinterConfig.default().rules[RULE_ID]["enabled"] is False


# ── URL extraction (no I/O) ──────────────────────────────────────


class TestUrlSelection:
    @pytest.mark.parametrize(
        "href,expected",
        [
            ("https://example.com/a", "https://example.com/a"),
            ("http://example.com/a?q=1#frag", "http://example.com/a?q=1"),
            # The IDNA codec passes pure-ASCII labels through verbatim, so
            # the lower-casing DNS and the `Host` header imply is ours to do.
            ("HTTPS://Example.com/a", "https://example.com/a"),
            ("https://Internal.Example.COM/wiki", "https://internal.example.com/wiki"),
            # Out of scope: not http(s), no host, or carrying credentials.
            ("mailto:someone@example.com", None),
            ("ftp://example.com/pub", None),
            ("app://connector/id", None),
            ("./docs/guide.md", None),
            ("#anchor", None),
            ("https:///nohost", None),
            ("https://user:token@example.com/a", None),
            # urlsplit raises on a malformed IPv6 literal.
            ("http://[::1/x", None),
        ],
    )
    def test_request_url(self, href, expected):
        target = ContentBrokenExternalReferenceRule._request_url(href)

        assert (target[0] if target else None) == expected

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
        # Liveness: the "never flagged" list below passes vacuously if
        # the run made no requests at all, so pin that it did.
        assert "/ok" in server.paths()
        joined = "\n".join(_messages(violations))
        for never_flagged in (
            "/forbidden",  # 403 bot wall
            "/rate-limited",  # 429 rate limit
            "/server-error",  # 5xx origin error
            "/redirect-loop",  # exceeds the hop cap
            "/redirect-ok",  # 302 -> 200
            "/ok",  # 200
            "/head-404-get-200",  # HEAD mis-implemented; GET says it is fine
            "/head-410-get-200",  # same, spelled 410
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

    def test_each_link_costs_one_probe_with_the_documented_methods(self, tmp_path, server):
        """Every link shape the AST yields, probed once, `GET` only where owed."""
        repo = _materialize("content/external-links", tmp_path, server.port)

        _run_rule(repo)

        expected = {
            # Repeated occurrences cost one probe, not one each: /ok and
            # /forbidden appear twice across the two files.
            "/ok": ["HEAD"],
            "/forbidden": ["HEAD"],
            # No GET for anything that was never a candidate violation.
            "/server-error": ["HEAD"],
            # /missing appears three times and still costs one probe —
            # HEAD plus the confirming GET, not three of them.
            "/missing": ["HEAD", "GET"],
            # A server that refuses HEAD outright gets the same retry.
            "/head-405": ["HEAD", "GET"],
            # The link shapes: an autolink `<http://…>`, a reference
            # link `[text][ref]`, and an image destination. The last one
            # surprises people — the commonest image in an instruction
            # file is a CI badge, and enabling this rule requests it.
            "/rate-limited": ["HEAD"],
            "/sla": ["HEAD"],
            "/badge.svg": ["HEAD"],
        }
        methods = _methods_by_path(server)

        assert {path: methods.get(path) for path in expected} == expected

    def test_out_of_scope_urls_are_neither_requested_nor_reported(self, tmp_path, server):
        repo = _materialize("content/external-links", tmp_path, server.port)

        violations = _run_rule(repo)

        assert "/ok" in server.paths(), "liveness: the run must have requested something"
        for marker, why in (
            # Inside a fence it is not a link in the AST at all.
            ("v1-chargebacks", "a URL in a fenced code block"),
            # Placeholder targets under templates/ are intentional, not
            # rot — exactly as content-broken-internal-reference has it.
            ("your-service", "a placeholder under templates/"),
        ):
            assert not [path for path in server.paths() if marker in path], why
            assert marker not in "\n".join(_messages(violations)), why

    def test_ignored_urls_are_never_requested(self, tmp_path, server):
        repo = _materialize("content/external-links", tmp_path, server.port)

        violations = _run_rule(
            repo,
            {"ignore": [f"http://127.0.0.1:{server.port}/missing", "*/gone"]},
        )

        assert "/ok" in server.paths()  # liveness
        assert "/missing" not in server.paths()
        assert "/gone" not in server.paths()
        joined = "\n".join(_messages(violations))
        assert "/missing" not in joined
        assert "/gone" not in joined

    @pytest.mark.parametrize("route", ["/head-405", "/head-501"])
    def test_both_head_rejection_codes_fall_back_to_get(self, route, server):
        rule = ContentBrokenExternalReferenceRule({"enabled": True}, allow_private_hosts=True)

        status, _checked = rule._probe(f"http://127.0.0.1:{server.port}{route}", 5.0, None)

        assert _methods_by_path(server)[route] == ["HEAD", "GET"]
        assert status == 404

    @pytest.mark.parametrize("hops,convicted", [(4, True), (9, False)])
    def test_the_hop_cap_binds_where_urllib_would_keep_going(self, hops, convicted, server):
        """`_MAX_REDIRECTS = 5` must actually bind.

        urllib's default is 10, so without the override the nine-hop
        chain would be followed all the way to its 404 and reported.
        `/redirect-loop` cannot prove this — a self-redirect trips
        `max_repeats` (4), which the rule leaves untouched.
        """
        rule = ContentBrokenExternalReferenceRule({"enabled": True}, allow_private_hosts=True)

        status, checked = rule._probe(f"http://127.0.0.1:{server.port}/hop/{hops}", 5.0, None)

        assert checked is True
        assert (status == 404) is convicted

    def test_redirect_out_of_http_is_not_followed(self, server):
        """A 302 into ``ftp://`` ends the chain instead of changing protocol."""
        rule = ContentBrokenExternalReferenceRule({"enabled": True}, allow_private_hosts=True)

        status, checked = rule._probe(f"http://127.0.0.1:{server.port}/redirect-ftp", 5.0, None)

        assert checked is True
        assert status not in (404, 410)
        assert server.paths() == ["/redirect-ftp"]

    def test_result_is_deterministic(self, tmp_path, server):
        repo = _materialize("content/external-links", tmp_path, server.port)

        first = _messages(_run_rule(repo))
        second = _messages(_run_rule(repo))

        assert first == second


# ── The operator's network controls ──────────────────────────────


def _rule_executing_argv(subcommand: str, repo: Path) -> List[str]:
    """Argv for one rule-executing subcommand against *repo*.

    All four run every enabled rule's ``check()``, so all four are
    network-executing and all four must honour the gate. ``fix``,
    ``baseline`` and ``badge`` write only inside the repository, which
    lives under ``tmp_path``.
    """
    argv = [subcommand, "-c", str(repo / ".skillsaw.yaml"), str(repo)]
    if subcommand == "lint":
        argv.extend(["--format", "json"])
    return argv


class TestOperatorNetworkGate:
    """``--no-network`` — the operator's refusal, which the repo cannot undo.

    The linted repository's ``.skillsaw.yaml`` decides whether the rule
    is *enabled*; only the operator decides whether skillsaw may touch
    the network at all. This mirrors ``--no-custom-rules`` (T1), the
    other repo-config-activated capability.
    """

    @pytest.mark.parametrize("subcommand", ["lint", "baseline", "badge"])
    @pytest.mark.parametrize("gate", ["--no-network", "SKILLSAW_NO_NETWORK"])
    def test_either_gate_stops_every_rule_executing_subcommand(
        self, gate, subcommand, tmp_path, server, monkeypatch
    ):
        """Behaviour, not `--help` text, on each subcommand that can probe.

        The flag is a hand-copied ``no_network=...`` keyword argument at
        each ``Linter(...)`` call site. Deleting one leaves the flag in
        ``--help``, leaves an argv-only test green, and silently makes
        the requests the operator refused. The variable is read by
        ``Linter`` itself, so no call site can miss that one — but only
        driving both proves it. The liveness half — that the same argv
        *does* reach the server ungated — is what keeps the gated half
        from passing vacuously. ``fix`` is absent because it never
        probes at all; see
        :meth:`test_fix_never_probes_whatever_the_flags_say`.
        """
        repo = _materialize("content/external-links", tmp_path, server.port)
        argv = _rule_executing_argv(subcommand, repo) + ["--allow-private-hosts"]

        run_cli(argv)
        assert server.hits, f"{subcommand} must reach the server without the gate"

        server.reset()
        if gate.startswith("--"):
            argv = argv + [gate]
        else:
            monkeypatch.setenv(gate, "1")
        run_cli(argv)

        assert server.hits == [], f"{subcommand} ignored {gate}"

    def test_fix_never_probes_whatever_the_flags_say(self, tmp_path, server):
        """``fix`` is offline unconditionally, not merely gateable.

        ``Linter.fix()`` calls ``check()`` on every loaded rule, fixable
        or not, and ``fix_and_apply()`` runs that up to ``max_passes``
        times — with a second ``Linter`` after an ``agentskill-name``
        rename — so a rule that probed here would sweep the whole URL set
        once per pass, each pass opening a fresh ``total-budget`` window.
        Every one of those results is discarded: ``fix`` displays fixes,
        and a dead URL has no mechanical fix. So ``fix`` forces
        ``no_network`` on rather than reading the flag, and the opt-in
        that makes the loopback fixture reachable buys it nothing.
        """
        repo = _materialize("content/external-links", tmp_path, server.port)

        # Liveness: the same repo, config and opt-in do reach the server
        # under `lint`, so the empty ledger below is the guarantee and
        # not a fixture that quietly stopped resolving.
        run_cli(_rule_executing_argv("lint", repo) + ["--allow-private-hosts"])
        assert server.hits, "the fixture must be reachable for this to mean anything"

        server.reset()
        result = run_cli(_rule_executing_argv("fix", repo) + ["--allow-private-hosts"])
        assert result.returncode == 0, result.stderr

        assert server.hits == [], "fix requested a URL, on some pass"

    def test_fix_with_only_a_network_rule_named_explains_itself(self, tmp_path, server):
        """The advice has to be advice the reader can act on.

        ``fix`` forces the gate on itself, so ``--rule <network rule>``
        empties its rule set and trips the same "nothing would be
        checked" guard ``lint`` has. On ``lint`` that guard says to drop
        ``--no-network``, which is right. Here it would name a flag the
        user never passed and cannot drop — ``fix`` set it — so the
        message has to point at ``lint`` instead. ``skillsaw fix --rule
        <id>`` is an invocation the shipped ``skillsaw-create-plugin``
        skill teaches, and any plugin rule declaring ``requires_network``
        reaches it too.
        """
        repo = _materialize("content/external-links", tmp_path, server.port)

        result = run_cli(["fix", "-c", str(repo / ".skillsaw.yaml"), str(repo), "--rule", RULE_ID])

        assert server.hits == []
        assert result.returncode == 1
        assert "drop --no-network" not in result.stderr, "the user never passed it"
        assert f"skillsaw lint --rule {RULE_ID}" in result.stderr

    def test_the_env_var_reaches_a_directly_constructed_linter(self, tmp_path, monkeypatch):
        """Not only the CLI: an embedder or a future subcommand too.

        The operator exports the variable for a whole job. If only
        ``no_network_requested(args)`` read it, the guarantee would rest
        on every future ``Linter(...)`` call site remembering to ask.
        """
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "CLAUDE.md").write_text("# Project\n\nBuild with make.\n", encoding="utf-8")
        monkeypatch.setenv("SKILLSAW_NO_NETWORK", "1")

        linter = Linter(RepositoryContext(repo), LinterConfig.default())

        assert linter._no_network is True

    def test_flag_beats_the_repository_config(self, tmp_path, server):
        repo = _materialize("content/external-links", tmp_path, server.port)

        result = run_lint(
            repo, "--allow-private-hosts", "--no-network", config=repo / ".skillsaw.yaml"
        )

        assert server.hits == []
        assert RULE_ID not in {v["rule_id"] for v in result["out"]["violations"]}
        assert "skipped (--no-network)" in result["stderr"]

    def test_the_gate_emptying_the_rule_set_is_an_error(self, tmp_path, server):
        """``--rule <network rule> --no-network`` must not exit 0 having done nothing.

        An org that exports ``SKILLSAW_NO_NETWORK`` job-wide and also
        runs the documented scheduled link-check recipe would otherwise
        get a permanently green job over an empty rule set — the quiet CI
        false pass REVIEW.md's T4/T12 bullet asks reviewers to flag.
        ``--no-custom-rules`` sets the precedent by failing loudly. Only
        an *empty* rule set is the error, not any dropped rule.
        """
        repo = _materialize("content/external-links", tmp_path, server.port)
        argv = ["--rule", RULE_ID, "--allow-private-hosts", "--no-network"]

        emptied = run_lint(repo, *argv, config=repo / ".skillsaw.yaml")

        assert server.hits == []
        assert emptied["rc"] != 0
        assert "skipped every rule named by --rule" in emptied["stderr"]
        assert RULE_ID in emptied["stderr"]

        survivor = run_lint(
            repo,
            *argv,
            "--rule",
            "content-broken-internal-reference",
            config=repo / ".skillsaw.yaml",
        )

        assert server.hits == []
        assert survivor["out"] is not None

    @pytest.mark.parametrize(
        "value,gates",
        [
            ("0", False),
            (" 0 ", False),
            ("false", False),
            ("FALSE", False),
            ("no", False),
            ("No", False),
            ("off", False),
            ("", False),
            ("1", True),
            ("true", True),
            ("TRUE", True),
            (" yes ", True),
            ("on", True),
            # A typo resolves toward refusing, not toward allowing:
            # `disabled` reads to a human like "the gate is disabled" and
            # turns it on instead. Deliberate for a variable that takes
            # capability away, and the opposite of how
            # `SKILLSAW_ALLOW_PRIVATE_HOSTS` resolves the same typo.
            ("maybe", True),
            ("disabled", True),
        ],
    )
    def test_the_env_var_resolves_every_spelling_toward_the_restriction(
        self, value, gates, tmp_path, server, monkeypatch
    ):
        repo = _materialize("content/external-links", tmp_path, server.port)
        monkeypatch.setenv("SKILLSAW_NO_NETWORK", value)

        run_lint(repo, "--allow-private-hosts", config=repo / ".skillsaw.yaml")

        assert (server.hits == []) is gates, f"SKILLSAW_NO_NETWORK={value!r}"

    @pytest.mark.parametrize(
        "value,granted",
        [
            ("1", True),
            ("true", True),
            (" YES ", True),
            ("on", True),
            ("0", False),
            ("false", False),
            ("", False),
            ("maybe", False),
            ("allow", False),
        ],
    )
    def test_the_private_host_permission_only_takes_an_explicit_yes(
        self, value, granted, tmp_path, server, monkeypatch
    ):
        """A permission resolves a typo by withholding itself."""
        repo = _materialize("content/external-links", tmp_path, server.port)
        monkeypatch.setenv("SKILLSAW_ALLOW_PRIVATE_HOSTS", value)

        run_lint(repo, config=repo / ".skillsaw.yaml")

        assert bool(server.hits) is granted

    def test_the_announcement_fires_exactly_when_the_rule_runs(self, tmp_path, server):
        """A real subprocess: the warnings registry is process-global.

        ``warnings.warn`` fires once per (message, category, location)
        per process under the default filters, so in-process runs would
        make this assertion depend on whether some earlier test in the
        same worker already triggered the notice. This is the
        "something a shared interpreter cannot give it" case that
        ``tests/cli_runner.py`` documents.
        """
        import subprocess
        import sys

        def _stderr_of_lint(repo: Path, *argv: str) -> str:
            return subprocess.run(
                [sys.executable, "-m", "skillsaw", "lint", *argv, str(repo)],
                capture_output=True,
                text=True,
                timeout=120,
            ).stderr

        enabled = _materialize("content/external-links", tmp_path / "on", server.port)
        announced = _stderr_of_lint(enabled, "-c", str(enabled / ".skillsaw.yaml"))

        assert "Network access enabled for" in announced
        assert RULE_ID in announced
        assert "--no-network" in announced
        assert "UserWarning" not in announced  # rendered, not the stock formatter

        unconfigured = _materialize(
            "content/external-links", tmp_path / "off", server.port, keep_config=False
        )

        assert "Network access enabled" not in _stderr_of_lint(unconfigured)

    def test_gate_is_declarative_not_a_rule_id_list(self):
        """A future network rule inherits the gate by declaring the attribute."""
        from skillsaw.rule import Rule

        assert Rule.requires_network is False
        assert ContentBrokenExternalReferenceRule.requires_network is True

    def test_a_custom_rule_declaring_the_attribute_is_gated_too(self, tmp_path):
        """Driven through the real custom-rule loader, not by calling the filter.

        The gate's claim is that it runs *after every loader*. A test
        that appends a rule to ``linter.rules`` and then calls
        ``_apply_network_gate()`` by hand verifies the filter but not
        that claim: move the call before ``_load_rules()``, or forget it
        on a future loader path, and this would still be green while a
        custom rule with ``requires_network`` ran under the flag.
        """
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "CLAUDE.md").write_text("# Project\n\nBuild with make.\n", encoding="utf-8")
        sentinel = tmp_path / "custom-rule-ran.txt"
        (repo / "custom_network_rule.py").write_text(
            "import pathlib\n"
            "from skillsaw.rule import Rule, Severity\n"
            "\n"
            "class NetworkCustomRule(Rule):\n"
            "    requires_network = True\n"
            "    default_enabled = True\n"
            "\n"
            "    @property\n"
            "    def rule_id(self):\n"
            "        return 'test-network-custom'\n"
            "\n"
            "    @property\n"
            "    def description(self):\n"
            "        return 'records that it ran'\n"
            "\n"
            "    def default_severity(self):\n"
            "        return Severity.INFO\n"
            "\n"
            "    def check(self, context):\n"
            f"        pathlib.Path({str(sentinel)!r}).write_text('ran')\n"
            "        return []\n",
            encoding="utf-8",
        )
        config = repo / ".skillsaw.yaml"
        config.write_text(
            'version: "99.0.0"\ncustom-rules:\n  - custom_network_rule.py\n', encoding="utf-8"
        )

        # Liveness: the rule really does load and run without the gate.
        run_cli(["lint", "--format", "json", "-c", str(config), str(repo)])
        assert sentinel.exists(), "the custom network rule must run without the gate"
        sentinel.unlink()

        run_cli(["lint", "--format", "json", "-c", str(config), str(repo), "--no-network"])

        assert not sentinel.exists(), "a custom rule declaring requires_network must be gated"


class TestUntrustedConfig:
    """``.skillsaw.yaml`` is untrusted repo content (THREAT_MODEL T13).

    Every option here is repo-controlled, so a hostile or mistyped value
    must degrade to the default — never to something more permissive
    than the default, and never to a hang.
    """

    # `check()` reads the settings and hands three numbers to `_probe_all`.
    _APPLIED_AS = {"timeout": "timeout", "total-budget": "budget", "concurrency": "concurrency"}

    @classmethod
    def _as_applied(cls, setting, value, monkeypatch):
        """The value `check()` actually hands `_probe_all` for *setting*."""
        rule = ContentBrokenExternalReferenceRule({"enabled": True, setting: value})
        seen = {}

        def _capture(urls, timeout, budget, concurrency):
            seen.update(timeout=timeout, budget=budget, concurrency=concurrency)
            return {}, 0

        monkeypatch.setattr(rule, "_probe_all", _capture)
        monkeypatch.setattr(rule, "_collect", lambda ctx: {"https://example.com/": []})

        rule.check(None)

        return seen[cls._APPLIED_AS[setting]]

    @pytest.mark.parametrize(
        "setting,value,expected",
        [
            # Non-finite and negative timeouts would mean an unbounded
            # socket timeout: T13's "hang CI forever". Both fall back to
            # the default rather than to the clamp ceiling — an operator
            # who wrote `inf` did not ask for 30 seconds either.
            ("timeout", float("inf"), 5.0),
            ("timeout", float("nan"), 5.0),
            ("timeout", -5, 0.1),
            ("timeout", 10_000, 30.0),
            ("timeout", "not-a-number", 5.0),
            ("timeout", None, 5.0),
            ("timeout", True, 5.0),
            ("total-budget", -1, 30.0),  # negative must not read as "no cap"
            ("total-budget", float("nan"), 30.0),
            ("total-budget", float("inf"), 30.0),
            ("total-budget", 0, 30.0),  # 0 is not "no cap" — it means the default
            ("total-budget", 10_000, 600.0),
            ("concurrency", 100_000, 32),
            ("concurrency", 0, 1),
            ("concurrency", -4, 1),
            ("concurrency", float("inf"), 8),
            ("concurrency", "many", 8),
        ],
    )
    def test_every_tuning_option_is_clamped(self, setting, value, expected, monkeypatch):
        assert self._as_applied(setting, value, monkeypatch) == pytest.approx(expected)

    def test_a_string_ignore_does_not_silence_every_url(self, tmp_path, server):
        """``ignore: "https://..."`` is the likeliest YAML mistake here.

        Iterating the string would yield single characters, and
        ``url.startswith("h")`` would then match every http(s) URL — the
        rule would report nothing while appearing to run.
        """
        repo = _materialize("content/external-links", tmp_path, server.port)

        violations = _run_rule(repo, {"ignore": f"http://127.0.0.1:{server.port}/missing"})

        assert server.paths(), "a mistyped ignore must not silence every request"
        assert violations

    def test_a_non_list_ignore_never_raises(self, tmp_path, server):
        repo = _materialize("content/external-links", tmp_path, server.port)

        assert _run_rule(repo, {"ignore": 5}) != []


class TestPrivateHostConfinement:
    """A repo must not aim the linter at its runner's internal network."""

    _REFUSED = [
        "http://127.0.0.1/x",
        "http://localhost/x",
        "https://sub.localhost/x",
        "http://[::1]/x",
        "http://10.0.0.5/x",
        "http://192.168.1.1/x",
        "http://172.16.0.1/x",
        # The cloud metadata endpoint — the canonical SSRF target (T18).
        "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
        # IPv4-mapped IPv6 must not launder a loopback address.
        "http://[::ffff:127.0.0.1]/x",
        "http://0.0.0.0/x",
        "http://[fe80::1]/x",
        "http://[::]/x",
        "http://[fd00::1]/x",
        # A trailing root dot and an uppercase name are the same host.
        "http://127.0.0.1./x",
        "http://LOCALHOST/x",
        # urllib percent-decodes the host before it connects, so a
        # confinement reading the string as authored sees a name
        # where the transport sees a literal — or a reserved name.
        "http://127%2E0%2E0%2E1/x",
        "http://loc%61lhost/x",
        # RFC 6598 carrier-grade NAT. `ipaddress` excludes 100.64.0.0/10
        # from `is_global` and from nothing else, so the six explicit
        # predicates all say "public" — and this is Tailscale's range
        # (100.100.100.100 is MagicDNS) plus several managed-Kubernetes
        # pod CIDRs, which makes it the private space a runner is most
        # likely to be able to reach.
        "http://100.64.0.1/x",
        "http://100.100.100.100/x",
        # A `%` that survives canonicalization is decoded a *second*
        # time by `Request._parse`, after which `http.client` reads a
        # decoded `:` as a port. Double encoding gets there, and so does
        # a single full-width `％` (U+FF05), which nameprep's NFKC step
        # folds to `%`.
        "http://169.254.169.254%253A80/latest/meta-data/",
        "http://127.0.0.1％3a8080/admin",
        "http://localhost％3A80/",
        "http://10.0.0.5%2540example.com/x",
        # `str.encode("idna")` passes pure-ASCII labels through verbatim,
        # checking only their length, so a NUL rides along: `inet_aton`
        # reads a name, `getaddrinfo` truncates at the NUL and resolves
        # loopback.
        "http://127.0.0.1%00.evil.com/x",
        # Userinfo the same decode *creates*. urllib does not strip it —
        # `Request('http://127.0.0.1@example.com/').host` is the whole
        # string — so the classified host and the resolved one differ.
        "http://user%40example.com/x",
        "http://127.0.0.1%40example.com/x",
        # Userinfo the decode creates in the *port* half. The port is as
        # much of the authority as the host is: `Request._parse` decodes
        # these into `169.254.169.254:80@x`, whose host is not the string
        # a confinement reading the tail as a port would classify — and
        # under an `http_proxy` the whole authority goes to a third-party
        # parser with no `http.client` split to fall back on.
        "http://169.254.169.254:80%40x/latest/meta-data/",
        "http://169.254.169.254:%40x/",
        "http://127.0.0.1:1%408.8.8.8/",
        "http://example.com:8%300/",
        # Percent-decoding can also put a bracket into the rebuilt
        # authority that the authored string never had, and `urlsplit`
        # refuses those. Refused, not raised: `ValueError` is outside
        # `_NETWORK_ERRORS`, so a link anywhere in a repository — or one
        # `Location` header — would otherwise become an unbaselinable
        # rule-execution-error.
        "http://example.com%5B/x",
        "http://example.com%5D/x",
        "http://%EF%BC%BB127.0.0.1%EF%BC%BD/x",
    ]

    @pytest.mark.parametrize("url", _REFUSED)
    def test_non_public_hosts_are_refused_by_default(self, url):
        rule = ContentBrokenExternalReferenceRule({"enabled": True})

        assert rule._admit(url) is None

    # Two ways a private address hides from a confinement that reads the
    # URL as written. The parser reaches one: `ipaddress.ip_address`
    # accepts only dotted-quad, while `inet_aton` — what the resolver
    # uses — also takes bare integers, hex, octal and short-dotted forms.
    # The transport reaches the other by *decoding*: `Request._parse`
    # percent-decodes the host, and `getaddrinfo` runs it through the
    # IDNA codec, whose nameprep applies NFKC and whose label splitter
    # treats U+3002, U+FF0E and U+FF61 as dots. Classifying any of these
    # as a hostname is how the metadata endpoint gets probed with the
    # confinement switched on.
    _ALTERNATE_SPELLINGS = [
        ("http://2852039166/latest/meta-data/", "169.254.169.254"),
        ("http://2130706433/x", "127.0.0.1"),
        ("http://0x7f000001/x", "127.0.0.1"),
        ("http://0177.0.0.1/x", "127.0.0.1"),
        ("http://127.1/x", "127.0.0.1"),
        ("http://0x7f.0.0.1/x", "127.0.0.1"),
        ("http://0/x", "0.0.0.0"),
        ("http://169%2E254%2E169%2E254/latest/meta-data/", "169.254.169.254"),
        ("http://%31%32%37.0.0.1/x", "127.0.0.1"),
        ("http://169。254。169。254/x", "169.254.169.254"),
        ("http://169．254．169．254/x", "169.254.169.254"),
        ("http://１２７.0.0.1/x", "127.0.0.1"),
        ("http://０x７f.0.0.1/x", "127.0.0.1"),
        ("http://①②⑦.0.0.1/x", "127.0.0.1"),
    ]

    @staticmethod
    def _on_the_wire(url: str) -> Tuple[str, str, str]:
        """``(host as authored, host as emitted, host urllib connects to)``.

        Computed from the stdlib rather than from the rule, so it is an
        independent statement of what urllib does — and it models
        **both** decodes, not one. The rule percent-decodes before the
        IDNA codec; ``urllib.request.Request._parse`` then percent-
        decodes whatever netloc it is handed, and ``http.client`` splits
        a decoded ``:`` off as a port. So the emitted host and the
        connected-to host are the same string only when nothing survives
        the first decode.
        """
        host = url.split("//", 1)[1].split("/", 1)[0]
        emitted = unquote(host).encode("idna").decode("ascii")
        return host, emitted, http.client.HTTPConnection(unquote(emitted)).host

    @pytest.mark.parametrize("url,canonical", _ALTERNATE_SPELLINGS)
    def test_non_canonical_ipv4_literals_are_refused(self, url, canonical):
        rule = ContentBrokenExternalReferenceRule({"enabled": True})

        # Liveness for the parametrize itself: each spelling really is
        # the address it claims to be, and really does defeat `ipaddress`.
        host, _emitted, wire = self._on_the_wire(url)
        with pytest.raises(ValueError):
            ipaddress.ip_address(host)
        assert socket.inet_ntoa(socket.inet_aton(wire)) == canonical

        assert rule._admit(url) is None

    @pytest.mark.parametrize("url", _REFUSED + [spelling for spelling, _ in _ALTERNATE_SPELLINGS])
    def test_refused_hosts_are_refused_as_redirect_hops_too(self, url):
        """`_accepts_hop` shares `_admit`, so the hop path must agree.

        Every entry, not only the numeric spellings: an origin picks the
        `Location` header, so a hop is the *more* hostile of the two
        paths into the confinement, not the less.
        """
        rule = ContentBrokenExternalReferenceRule({"enabled": True})

        assert rule._accepts_hop(url) is False

    # The percent-decode urllib performs on the netloc it is handed,
    # which is the one the rule's own canonicalization cannot see.
    # Each row names the host and port `http.client` would connect to
    # if a `%` were allowed to survive into the requested URL.
    _SURVIVING_PERCENT = [
        ("http://169.254.169.254%253A80/latest/meta-data/", "169.254.169.254", 80),
        ("http://127.0.0.1％3a8080/admin", "127.0.0.1", 8080),
        ("http://localhost％3A80/", "localhost", 80),
        ("http://10.0.0.5%2540example.com/x", "10.0.0.5@example.com", 80),
    ]

    @pytest.mark.parametrize("url,wire_host,wire_port", _SURVIVING_PERCENT)
    def test_a_second_percent_decode_cannot_smuggle_a_private_host(self, url, wire_host, wire_port):
        """A host the transport would decode again is refused, not classified.

        Liveness first, from the stdlib: canonicalizing these once
        leaves a `%` behind, and urllib's own decode then turns it into
        a port separator or userinfo. Classifying the once-decoded
        string would therefore be classifying a host nothing connects
        to — so the refusal has to happen even under the operator's
        opt-in, which is what this asserts.
        """
        authored = url.split("//", 1)[1].split("/", 1)[0]
        once = unquote(authored).encode("idna").decode("ascii")
        assert "%" in once, "premise: one decode does not settle this host"
        connection = http.client.HTTPConnection(unquote(once))
        assert (connection.host, connection.port) == (wire_host, wire_port)

        rule = ContentBrokenExternalReferenceRule({"enabled": True}, allow_private_hosts=True)

        assert rule._admit(url) is None

    # The port half, which `_canonical_netloc` used to carry through
    # verbatim. Each row names the authority `Request._parse` decodes it
    # into, whose host is not the one a confinement reading that tail as
    # a port would classify.
    _SMUGGLED_IN_THE_PORT = [
        ("http://169.254.169.254:80%40x/latest/meta-data/", "169.254.169.254:80@x"),
        ("http://169.254.169.254:%40x/", "169.254.169.254:@x"),
        ("http://127.0.0.1:1%408.8.8.8/", "127.0.0.1:1@8.8.8.8"),
        ("http://example.com:8%300/", "example.com:800"),
        # The bracketed branch validates its port too, and this is the
        # only row that binds it: the host half is public, so nothing
        # else refuses it.
        ("http://[2606:4700::1]:8%300/x", "[2606:4700::1]:800"),
    ]

    @pytest.mark.parametrize("url,decoded", _SMUGGLED_IN_THE_PORT)
    def test_a_port_that_decodes_into_something_else_is_refused(self, url, decoded):
        """Refused outright, so the operator's opt-in does not skip it.

        `_admit` consults `_is_public_host` only when the operator has
        *not* opted in, so a port validated there would be unvalidated by
        anything under `--allow-private-hosts`. Validating it where the
        authority is rebuilt is what makes the refusal unconditional.
        """
        authored = url.split("//", 1)[1].split("/", 1)[0]
        assert unquote(authored) == decoded, "premise: urllib decodes this authority"

        rule = ContentBrokenExternalReferenceRule({"enabled": True}, allow_private_hosts=True)

        assert rule._admit(url) is None

    def test_a_control_character_cannot_hide_a_literal_behind_a_name(self):
        """`getaddrinfo` truncates at a NUL; `inet_aton` refuses it.

        So `127.0.0.1\\x00.evil.com` is a name to the confinement and
        loopback to the resolver. Today `http.client` also refuses it,
        but that is a downstream guard against a different problem —
        the confinement has to reach the same verdict on its own.
        """
        url = "http://127.0.0.1%00.evil.com/x"
        smuggled = unquote("127.0.0.1%00.evil.com").encode("idna").decode("ascii")
        assert socket.getaddrinfo(smuggled, 80, flags=socket.AI_NUMERICHOST)[0][4][0] == "127.0.0.1"
        with pytest.raises(ValueError):
            socket.inet_aton(smuggled)

        rule = ContentBrokenExternalReferenceRule({"enabled": True}, allow_private_hosts=True)

        assert rule._admit(url) is None

    @pytest.mark.parametrize("url,_canonical", _ALTERNATE_SPELLINGS)
    def test_the_operator_can_still_reach_them(self, url, _canonical):
        """Refusal is the confinement, not a parse failure.

        Without this, a normalization that simply rejected every
        numeric-looking host would pass the tests above while breaking
        the operator's opt-in. What comes back carries the host the
        transport will spell, so the URL that is requested and the one
        matched against ``ignore`` are the one the confinement
        classifies. The *reported* URL is deliberately not in that list:
        the message names the authored href, which is the string the
        user has to find in the file.
        """
        rule = ContentBrokenExternalReferenceRule({"enabled": True}, allow_private_hosts=True)

        host, emitted, wire = self._on_the_wire(url)
        # Nothing survives the first decode for these spellings, so the
        # host the rule emits is already the one urllib connects to.
        assert emitted == wire

        assert rule._admit(url) == url.replace(host, emitted, 1)

    def test_ignore_sees_the_url_the_transport_will_request(self):
        """``ignore`` matches the URL the transport will request.

        An operator keeps skillsaw off an internal host by naming it in
        ``ignore``. Matching the string as authored instead would let a
        percent-encoded — or merely capitalized — spelling of that host
        through, the same way such a spelling would slip past the
        public-host confinement. The IDNA codec case-folds nothing on
        pure-ASCII labels, so the lower-casing is the rule's own.
        """
        rule = ContentBrokenExternalReferenceRule(
            {"enabled": True, "ignore": ["https://intranet.example.com/"]},
            allow_private_hosts=True,
        )

        assert rule._admit("https://intranet%2Eexample%2Ecom/wiki") is None
        assert rule._admit("https://Intranet.Example.COM/wiki") is None
        assert rule._admit("https://other.example.com/wiki") is not None

    def test_both_operands_of_an_ignore_glob_are_length_bounded(self):
        """`fnmatch` gets no unbounded input from either side (T13).

        `_is_ignored` compiles a `.skillsaw.yaml` glob through
        `fnmatch.translate` and matches it against a URL from the same
        repository, so both operands are repo-controlled. Not a
        backtracking mitigation — `fnmatch.translate` has emitted the
        linear emulation since 3.9 (bpo-40480) — a size one: it bounds
        the compiled pattern, the subject, and, for the URL, the
        violation message and the de-duplication key it also becomes.
        """
        long_url = "https://example.com/" + "a" * _MAX_URL_LENGTH
        assert len(long_url) > _MAX_URL_LENGTH
        assert (
            ContentBrokenExternalReferenceRule({"enabled": True}, allow_private_hosts=True)._admit(
                long_url
            )
            is None
        )

        # An over-long pattern is skipped rather than compiled, so the
        # URL it would have matched is probed instead of ignored. Kept
        # deliberately benign: the point is which branch runs, and a
        # pathological pattern here would hang rather than fail.
        pattern = "https://h/" + "x" * _MAX_IGNORE_PATTERN_LENGTH + "*"
        assert len(pattern) > _MAX_IGNORE_PATTERN_LENGTH
        rule = ContentBrokenExternalReferenceRule(
            {"enabled": True, "ignore": [pattern]}, allow_private_hosts=True
        )

        assert rule._admit("https://h/" + "x" * _MAX_IGNORE_PATTERN_LENGTH + "y") is not None

    @pytest.mark.parametrize(
        "url",
        ["https://example.com/x", "https://8.8.8.8/x", "http://[2606:4700::1]/x"],
    )
    def test_public_hosts_are_admitted(self, url):
        rule = ContentBrokenExternalReferenceRule({"enabled": True})

        assert rule._admit(url) == url

    def test_confinement_makes_the_loopback_fixture_unreachable(self, tmp_path, server):
        """Without the opt-in, the whole scripted server is off limits."""
        repo = _materialize("content/external-links", tmp_path, server.port)

        violations = _run_rule(repo, allow_private_hosts=False)

        assert violations == []
        assert server.hits == []

    def test_a_repo_config_key_cannot_grant_private_access(self, tmp_path, server):
        """The control is operator-only; `.skillsaw.yaml` has no say.

        A repo that could write `allow-private-hosts: true` would be
        disabling the confinement that exists to contain it (T18). The
        key is not in `config_schema`, so writing it lands in the
        settings dict as an unrecognized option and must change nothing.
        """
        repo = _materialize("content/external-links", tmp_path, server.port)

        violations = _run_rule(repo, {"allow-private-hosts": True}, allow_private_hosts=False)

        assert violations == []
        assert server.hits == []
        assert "allow-private-hosts" not in ContentBrokenExternalReferenceRule.config_schema


class TestRedirectTargetsAreVetted:
    """Admission runs on every hop, not only on the authored URL."""

    def test_redirect_into_an_ignored_host_is_not_followed(self, tmp_path, server):
        """Otherwise ``ignore`` is bypassable by any origin that answers 302."""
        rule = ContentBrokenExternalReferenceRule(
            {"enabled": True, "ignore": [f"http://127.0.0.1:{server.port}/relocated"]},
            allow_private_hosts=True,
        )

        status, checked = rule._probe(f"http://127.0.0.1:{server.port}/redirect-missing", 5.0, None)

        assert server.paths() == ["/redirect-missing"]  # the hop was refused
        assert checked is True
        assert status not in (404, 410)

    def test_a_hop_faces_the_whole_authored_url_gate(self):
        """A public URL must not be able to walk the linter inside."""
        rule = ContentBrokenExternalReferenceRule({"enabled": True})

        assert rule._accepts_hop("http://169.254.169.254/latest/") is False
        assert rule._accepts_hop("https://user:token@example.com/x") is False
        assert rule._accepts_hop("https://example.com/ok") is True

    def test_a_malformed_location_header_is_inconclusive(self, server):
        """A remote party must not be able to raise out of the probe.

        The base ``http_error_302`` parses the raw ``Location`` header
        before ``redirect_request`` runs, so the admission gate never
        sees it and the ``ValueError`` lands in the caller. ``ValueError``
        is deliberately outside ``_NETWORK_ERRORS`` — it means a bug in
        this rule — so any hostile or broken origin could otherwise turn
        an opted-in run into an unbaselinable ``rule-execution-error``.
        """
        # Premise: the header really does defeat the stdlib's parser.
        with pytest.raises(ValueError):
            urlparse("http://[::1/x")

        rule = ContentBrokenExternalReferenceRule({"enabled": True}, allow_private_hosts=True)

        status, checked = rule._probe(
            f"http://127.0.0.1:{server.port}/redirect-malformed", 5.0, None
        )

        assert server.paths() == ["/redirect-malformed"]
        assert checked is True
        assert status not in (404, 410)


class TestNoBodyIsEverRead:
    """Not the final response's, and not an intermediate redirect's.

    ``HTTPRedirectHandler.http_error_302`` calls ``fp.read()`` on the hop
    it is leaving, before it opens the next one — an uncapped read of a
    body nothing here wants. On the GET confirmation path that body is
    chosen by the origin, and the socket timeout is re-armed on every
    ``recv``, so an endless chunked stream would be read into the
    worker's memory for as long as bytes keep arriving.
    """

    @staticmethod
    def _handler(hop_timeout=1.0):
        opened = []
        handler = _BoundedRedirectHandler(lambda url: True, lambda: hop_timeout)
        handler.parent = SimpleNamespace(
            open=lambda new, timeout=None: opened.append((new.full_url, timeout))
        )
        return handler, opened

    @staticmethod
    def _headers(location: str):
        return email.message_from_string(f"Location: {location}\n", _class=http.client.HTTPMessage)

    @staticmethod
    def _recording_body(reads, closed):
        class _Recording:
            def read(self, *args):
                reads.append(args)
                return b"x" * 4096

            def close(self):
                closed.append(True)

        return _Recording()

    @pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
    def test_the_hop_body_is_not_read_on_any_redirect_code(self, code):
        """The base class aliases all of them, so overriding 302 alone is not enough."""
        reads, closed = [], []
        handler, opened = self._handler()
        method = getattr(handler, f"http_error_{code}", None)
        if method is None:  # pragma: no cover - 308 predates 3.11 only
            pytest.skip(f"urllib has no http_error_{code} on this interpreter")
        request = urllib.request.Request("http://127.0.0.1:1/from")
        request.timeout = 30.0

        method(
            request,
            self._recording_body(reads, closed),
            code,
            "Found",
            self._headers("http://127.0.0.1:1/to"),
        )

        assert reads == []
        assert closed == [True]  # still released, just never drained
        assert [url for url, _timeout in opened] == ["http://127.0.0.1:1/to"]

    def test_each_hop_gets_the_remainder_of_the_window_not_the_full_timeout(self):
        """Otherwise a five-hop chain costs five timeouts instead of one."""
        handler, opened = self._handler(hop_timeout=0.75)
        request = urllib.request.Request("http://127.0.0.1:1/from")
        request.timeout = 30.0

        handler.http_error_302(
            request,
            _EmptyBody(SimpleNamespace(close=lambda: None)),
            302,
            "Found",
            self._headers("http://127.0.0.1:1/to"),
        )

        assert opened == [("http://127.0.0.1:1/to", 0.75)]

    def test_a_refused_hop_still_reads_nothing(self):
        reads, closed = [], []
        handler, _opened = self._handler()
        handler._accepts = lambda url: False
        request = urllib.request.Request("http://127.0.0.1:1/from")
        request.timeout = 30.0

        with pytest.raises(urllib.error.HTTPError):
            handler.http_error_302(
                request,
                self._recording_body(reads, closed),
                302,
                "Found",
                self._headers("http://169.254.169.254/x"),
            )

        assert reads == []


class TestHeadIsNeverEnoughToConvict:
    """A candidate violation is confirmed with GET before it is reported.

    RFC 9110 requires a HEAD response to be what GET would return minus
    the body. Real servers disagree: nvlpubs.nist.gov answers 404 to HEAD
    for its copy of NIST SP 800-53r5 and serves the PDF on GET, and
    azure.microsoft.com does the same on some marketing paths. A HEAD
    answer alone would report those live pages as dead.
    """

    def test_get_settles_it_in_both_directions(self, tmp_path, server):
        """A mis-implemented HEAD is acquitted; a link really gone is not."""
        repo = _materialize("content/external-links", tmp_path, server.port)

        violations = _run_rule(repo)

        reported = "\n".join(_messages(violations))
        methods = _methods_by_path(server)
        for acquitted in ("/head-404-get-200", "/head-410-get-200"):
            assert acquitted not in reported
            assert methods[acquitted] == ["HEAD", "GET"]
        assert "/missing" in reported
        assert methods["/missing"] == ["HEAD", "GET"]

    def test_unconfirmable_404_stays_silent(self, monkeypatch):
        """A budget that expires mid-confirmation reports nothing.

        The HEAD said 404 but the GET never happened, so nothing was
        proven — and an unconfirmed status must never be reported.
        Requests are stubbed so the budget, not the network, decides.
        """
        rule = ContentBrokenExternalReferenceRule({"enabled": True})
        calls = []

        def _burn_the_budget(url, method, timeout):
            calls.append(method)
            threading.Event().wait(0.25)
            return 404

        monkeypatch.setattr(rule, "_request", _burn_the_budget)

        status, checked = rule._probe(
            "http://127.0.0.1:1/never-reached", 5.0, time.monotonic() + 0.2
        )

        assert calls == ["HEAD"]  # the confirming GET never ran
        assert checked is True
        assert status is None  # not 404 — nothing was proven


# ── Failure modes that must stay silent ──────────────────────────


class TestInconclusiveOutcomesAreNeverReported:
    """Everything the network can say about itself produces no violation."""

    def test_offline_produces_no_violations(self, tmp_path, closed_port):
        """Connection refused says nothing about the link."""
        repo = _materialize("content/external-links", tmp_path, closed_port)

        assert _run_rule(repo) == []

    def test_unresolvable_host_produces_no_violations(self, temp_dir, monkeypatch):
        """DNS failure is inconclusive — and is simulated, not performed.

        ``host.invalid`` is reserved by RFC 2606, but resolving it still
        puts a query on the wire, and a resolver with search domains and
        wildcard DNS (corporate networks, captive portals) can answer it.
        Patching ``getaddrinfo`` exercises the same branch with zero
        packets, which is what this module promises.
        """
        (temp_dir / "CLAUDE.md").write_text(
            "# Project\n\n"
            "Read the [design notes](https://notes.example.com/design.md) before "
            "changing the parser.\n",
            encoding="utf-8",
        )

        def _nxdomain(*args, **kwargs):
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")

        monkeypatch.setattr(socket, "getaddrinfo", _nxdomain)

        assert _run_rule(temp_dir) == []

    def test_timeout_produces_no_violations(self, tmp_path, server):
        repo = _materialize("content/external-links-slow", tmp_path, server.port)

        violations = _run_rule(repo, {"timeout": 0.5, "total-budget": 30, "concurrency": 2})

        assert violations == []


# ── The wall-clock budget ────────────────────────────────────────


class TestBudgetExhaustion:
    """A run that ran out of time says so, once, and never convicts."""

    def test_an_exhausted_budget_emits_one_baselinable_info_notice(self, tmp_path, server):
        """One notice, and one carrying no count, so it can be baselined.

        It has no file, so baseline identity falls through to hashing
        rule_id + message. A count that moves with runner latency would
        re-fingerprint the notice on every run — impossible to baseline,
        and a new finding every time under ``fail-on: info``.
        """
        repo = _materialize("content/external-links-slow", tmp_path, server.port)

        # One worker, a one-second budget, two URLs that never answer: the
        # first burns the budget, the second is never requested.
        violations = _run_rule(repo, {"timeout": 5, "total-budget": 1, "concurrency": 1})
        requested = len(server.paths())
        shorter = _run_rule(repo, {"timeout": 5, "total-budget": 0.5, "concurrency": 1})

        assert requested == 1
        assert len(violations) == 1
        notice = violations[0]
        assert notice.severity == Severity.INFO
        assert "left unchecked" in notice.message
        assert "network budget" in notice.message
        assert notice.fingerprint_discriminator == "network-budget-exhausted"
        assert not any(char.isdigit() for char in notice.message)
        assert notice.message == shorter[0].message  # stable across budgets

    def test_no_notice_when_nothing_was_skipped(self, tmp_path, server):
        repo = _materialize("content/external-links", tmp_path, server.port)

        violations = _run_rule(repo)

        assert not any("unchecked" in v.message for v in violations)

    def test_the_budget_notice_survives_the_cli(self, tmp_path, server):
        """End to end: a path-less INFO violation still serializes and exits 0.

        The notice has no ``file_path`` and no ``line``. Nothing else
        checks that such a violation reaches the JSON report intact, or
        that an INFO-only run does not flip the exit code.
        """
        repo = _materialize("content/external-links-slow", tmp_path, server.port)

        result = run_lint(repo, "--allow-private-hosts", config=repo / ".skillsaw.yaml")

        notices = [
            v
            for v in result["out"]["violations"]
            if v["rule_id"] == RULE_ID and "left unchecked" in v["message"]
        ]
        assert len(notices) == 1
        assert notices[0]["severity"] == "info"
        assert notices[0]["file_path"] is None
        assert notices[0]["line"] is None
        assert result["rc"] == 0
        # The count the message deliberately omits is on the -v log.
        assert "external URLs unchecked" in result["stderr"]


class TestTheRunIsBounded:
    """The wall clock, not a cooperative socket timeout, ends the run.

    ``timeout`` is a socket timeout: urllib re-arms it on every read, so
    an origin that dribbles one byte just under it holds a worker
    indefinitely. ``total-budget`` is what actually bounds the run, and
    it bounds it by abandoning workers rather than by waiting for them.
    """

    def test_workers_that_never_return_are_abandoned(self, monkeypatch):
        """No socket: `_probe` itself blocks, so only the join can end this."""
        rule = ContentBrokenExternalReferenceRule({"enabled": True})
        blocked = threading.Event()

        def _never_answers(url, timeout, deadline):
            blocked.wait(30)  # finite so a failing run does not leak a thread
            return 200, True

        monkeypatch.setattr(rule, "_probe", _never_answers)
        urls = [f"https://example.com/{n}" for n in range(4)]

        started = time.monotonic()
        try:
            statuses, unchecked = rule._probe_all(urls, timeout=0.2, budget=0.3, concurrency=4)
            elapsed = time.monotonic() - started
        finally:
            blocked.set()

        assert statuses == {}
        assert unchecked == len(urls)
        # The load-bearing half: this is what fails if the join ever
        # starts waiting for the workers instead of abandoning them.
        assert elapsed < 5.0

    def test_probe_threads_are_daemons(self):
        """Abandoned is not enough — they must not hold the interpreter open.

        ``concurrent.futures`` registers an atexit hook that joins every
        live pool worker, so a ThreadPoolExecutor here would bound
        ``check()``'s return without bounding the process: the report
        prints and the exit code is never delivered.
        """
        rule = ContentBrokenExternalReferenceRule({"enabled": True})
        seen = []

        def _record(url, timeout, deadline):
            seen.append(threading.current_thread().daemon)
            return None, False

        rule._probe = _record
        rule._probe_all(["https://example.com/a"], timeout=1.0, budget=5.0, concurrency=1)

        assert seen == [True]

    def test_a_bug_in_the_rule_is_not_swallowed_as_a_network_failure(self):
        """`_NETWORK_ERRORS` must stay narrow, and `_probe_all` must re-raise.

        Widening it to ``except Exception`` — the natural "make it more
        robust" edit — would turn a ``TypeError`` into "nothing to
        report" and let the run exit 0 looking healthy. The linter's
        contract is that a rule bug becomes an unbaselinable
        ``rule-execution-error`` instead.
        """
        rule = ContentBrokenExternalReferenceRule({"enabled": True})

        def _explode(url, timeout, deadline):
            raise TypeError("a bug in the rule, not a network condition")

        rule._probe = _explode

        with pytest.raises(TypeError):
            rule._probe_all(["https://example.com/a"], timeout=1.0, budget=5.0, concurrency=1)

    @pytest.mark.parametrize(
        "raised,swallowed",
        [
            (socket.timeout("timed out"), True),  # the network failing
            (AttributeError("typo in the rule"), False),  # a bug in the rule
        ],
    )
    def test_request_swallows_the_network_and_only_the_network(
        self, raised, swallowed, monkeypatch
    ):
        """The same contract one level down, where `_NETWORK_ERRORS` applies."""
        rule = ContentBrokenExternalReferenceRule({"enabled": True})

        class _Opener:
            def open(self, request, timeout=None):
                raise raised

        monkeypatch.setattr(rule, "_opener", lambda: _Opener())

        if swallowed:
            assert rule._request("https://example.com/a", "HEAD", 1.0) is None
        else:
            with pytest.raises(type(raised)):
                rule._request("https://example.com/a", "HEAD", 1.0)


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

        The assertion is on a recorded ledger, not on a raised exception.
        ``Linter.run`` catches every ``Exception`` from a rule — including
        ``AssertionError`` — and converts it into a ``rule-execution-error``
        violation, so a tripwire that only raised would be swallowed and
        the test would pass whether or not a rule reached the network.
        Both halves matter: an empty ledger, and no crash hiding in the
        returned violations.
        """
        repo = _materialize("content/external-links", tmp_path, server.port, keep_config=False)
        attempts = []

        def _refuse(self, address, *args, **kwargs):
            attempts.append(address)
            raise OSError("a default lint run must not open a socket")

        monkeypatch.setattr(socket.socket, "connect", _refuse)
        monkeypatch.setattr(socket.socket, "connect_ex", _refuse)
        monkeypatch.setattr(
            socket, "getaddrinfo", lambda *a, **k: attempts.append(a) or []  # noqa: B018
        )

        found = Linter(RepositoryContext(repo), LinterConfig.default()).run()

        assert attempts == []
        assert [v for v in found if v.rule_id == "rule-execution-error"] == []
        assert server.hits == []

    @pytest.mark.parametrize(
        "rule_config,argv,requests",
        [
            # ANY non-`enabled` key turns a disabled-by-default rule on:
            # `config.rule_enabled_reason` answers "configured in config
            # (overrides disabled-by-default)" for a lone `timeout:` or
            # `severity:`. The rule doc states it, and it is the single
            # most hermeticity-relevant behaviour in the feature.
            ("    timeout: 5\n", ["--allow-private-hosts"], True),
            # The documented escape hatch: settings without activation.
            ("    enabled: false\n    timeout: 5\n", [], False),
            # `--rule` is the documented entry point, and nothing else
            # pins it: making it a pure filter over already-enabled rules
            # would break every invocation the docs recommend while the
            # rest of the suite stayed green.
            (
                "    enabled: false\n",
                ["--rule", RULE_ID, "--allow-private-hosts"],
                True,
            ),
        ],
    )
    def test_what_activates_a_disabled_by_default_rule(
        self, rule_config, argv, requests, tmp_path, server
    ):
        repo = _materialize("content/external-links", tmp_path, server.port, keep_config=False)
        (repo / ".skillsaw.yaml").write_text(
            'version: "99.0.0"\nrules:\n' f"  {RULE_ID}:\n{rule_config}", encoding="utf-8"
        )

        result = run_lint(repo, *argv, config=repo / ".skillsaw.yaml")

        assert bool(server.hits) is requests
        fired = {v["rule_id"] for v in result["out"]["violations"]}
        assert (RULE_ID in fired) is requests

    def test_enabling_the_rule_is_what_turns_the_network_on(self, tmp_path, server):
        repo = _materialize("content/external-links", tmp_path, server.port)

        result = run_lint(repo, "--allow-private-hosts", config=repo / ".skillsaw.yaml")

        fired = [v for v in result["out"]["violations"] if v["rule_id"] == RULE_ID]
        assert len(fired) == 6
        assert server.hits != []
        assert {v["file_path"] for v in fired} == {
            "CLAUDE.md",
            "skills/release-checklist/SKILL.md",
        }
        assert all(v["line"] for v in fired)

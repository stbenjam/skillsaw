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
import time
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

    # path -> (status, Location or None). Redirect targets are distinct
    # from the plain routes so the de-duplication test can count requests
    # to /missing without redirect traffic landing there.
    ROUTES = {
        "/ok": (200, None),
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
    }

    def _handle(self, method: str):
        path = self.path
        self.server.hits.append((method, path))
        if path in self.ROUTES:
            status, location = self.ROUTES[path]
            self._respond(status, location=location, body=b"body")
        elif path == "/head-405":
            # Rejects HEAD outright; the GET retry finds it is gone.
            self._respond(405 if method == "HEAD" else 404, body=b"")
        elif path == "/head-501":
            # The other spelling of "this server will not do HEAD".
            self._respond(501 if method == "HEAD" else 404, body=b"")
        elif path.startswith("/hop/"):
            # A chain of DISTINCT hops, so it trips the hop cap rather
            # than urllib's untouched same-URL max_repeats.
            step = int(path.rsplit("/", 1)[1])
            if step <= 1:
                self._respond(404, body=b"end of chain")
            else:
                self._respond(302, location=f"/hop/{step - 1}")
        elif path == "/head-404-get-200":
            # nvlpubs.nist.gov's shape: 404 to HEAD, serves it on GET.
            self._respond(404 if method == "HEAD" else 200, body=b"body")
        elif path == "/head-410-get-200":
            # The same mis-implementation spelled with 410.
            self._respond(410 if method == "HEAD" else 200, body=b"body")
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


def _run_rule(repo: Path, config: dict = None):
    # allow-private-hosts is required for the loopback server to be
    # reachable at all — the rule refuses non-public hosts by default.
    # Tests that exercise that refusal override it back to False.
    settings = {"enabled": True, "allow-private-hosts": True}
    settings.update(config or {})
    rule = ContentBrokenExternalReferenceRule(settings)
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
            # urlsplit raises on a malformed IPv6 literal.
            ("http://[::1/x", None),
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

        # Liveness: every "not requested" assertion below passes vacuously
        # if the run made no requests at all, so pin that it did.
        assert "/ok" in server.paths()
        assert violations, "the fixture must still produce real findings"
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

    def test_each_url_is_probed_once(self, tmp_path, server):
        """Repeated occurrences of one URL cost one probe, not one each."""
        repo = _materialize("content/external-links", tmp_path, server.port)

        _run_rule(repo)

        methods = _methods_by_path(server)
        # /ok and /forbidden each appear twice across the two files.
        assert methods["/ok"] == ["HEAD"]
        assert methods["/forbidden"] == ["HEAD"]
        # /missing appears three times and still costs one probe — which
        # is HEAD plus the confirming GET, not three of them.
        assert methods["/missing"] == ["HEAD", "GET"]

    def test_healthy_links_cost_a_single_head(self, tmp_path, server):
        repo = _materialize("content/external-links", tmp_path, server.port)

        _run_rule(repo)

        methods = _methods_by_path(server)
        # No GET for anything that was never a candidate violation.
        assert methods["/ok"] == ["HEAD"]
        assert methods["/rate-limited"] == ["HEAD"]
        assert methods["/server-error"] == ["HEAD"]

    def test_head_rejection_falls_back_to_get(self, tmp_path, server):
        repo = _materialize("content/external-links", tmp_path, server.port)

        _run_rule(repo)

        assert _methods_by_path(server)["/head-405"] == ["HEAD", "GET"]

    def test_urls_in_code_fences_are_never_requested(self, tmp_path, server):
        repo = _materialize("content/external-links", tmp_path, server.port)

        violations = _run_rule(repo)

        assert "/ok" in server.paths()  # liveness
        assert "/v1-chargebacks" not in server.paths()
        assert "v1-chargebacks" not in "\n".join(_messages(violations))

    def test_autolinks_are_collected(self, tmp_path, server):
        """``<http://…>`` is a link in the AST and is probed like any other."""
        repo = _materialize("content/external-links", tmp_path, server.port)

        _run_rule(repo)

        assert "/rate-limited" in server.paths()

    def test_template_directories_are_skipped(self, tmp_path, server):
        """Placeholder targets under templates/ are intentional, not rot."""
        repo = _materialize("content/external-links", tmp_path, server.port)

        violations = _run_rule(repo)

        assert "/ok" in server.paths()  # liveness
        assert not [p for p in server.paths() if "template" in p]
        assert "template" not in "\n".join(_messages(violations))

    def test_image_destinations_are_probed(self, tmp_path, server):
        """Badge URLs in a CLAUDE.md are images, and images are links.

        Worth pinning because it surprises people: the most common image
        destination in an instruction file is a CI or coverage badge, and
        enabling this rule starts requesting them.
        """
        repo = _materialize("content/external-links", tmp_path, server.port)

        _run_rule(repo)

        assert "/badge.svg" in server.paths()

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
        rule = ContentBrokenExternalReferenceRule({"enabled": True, "allow-private-hosts": True})

        status, _checked = rule._probe(f"http://127.0.0.1:{server.port}{route}", 5.0, None)

        assert _methods_by_path(server)[route] == ["HEAD", "GET"]
        assert status == 404

    def test_a_chain_within_the_hop_cap_is_followed_to_its_404(self, server):
        rule = ContentBrokenExternalReferenceRule({"enabled": True, "allow-private-hosts": True})

        status, _checked = rule._probe(f"http://127.0.0.1:{server.port}/hop/4", 5.0, None)

        assert status == 404

    def test_a_chain_past_the_hop_cap_is_abandoned(self, server):
        """`_MAX_REDIRECTS = 5` must actually bind.

        urllib's default is 10, so without the override this chain would
        be followed all the way to its 404 and reported. `/redirect-loop`
        cannot prove this — a self-redirect trips `max_repeats` (4),
        which the rule leaves untouched.
        """
        rule = ContentBrokenExternalReferenceRule({"enabled": True, "allow-private-hosts": True})

        status, checked = rule._probe(f"http://127.0.0.1:{server.port}/hop/9", 5.0, None)

        assert checked is True
        assert status not in (404, 410)

    def test_redirect_out_of_http_is_not_followed(self, server):
        """A 302 into ``ftp://`` ends the chain instead of changing protocol."""
        rule = ContentBrokenExternalReferenceRule({"enabled": True, "allow-private-hosts": True})

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


class TestOperatorNetworkGate:
    """``--no-network`` — the operator's refusal, which the repo cannot undo.

    The linted repository's ``.skillsaw.yaml`` decides whether the rule
    is *enabled*; only the operator decides whether skillsaw may touch
    the network at all. This mirrors ``--no-custom-rules`` (T1), the
    other repo-config-activated capability.
    """

    @pytest.mark.parametrize("subcommand", ["lint", "fix", "baseline", "badge"])
    def test_flag_exists_on_every_rule_executing_subcommand(self, subcommand):
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-m", "skillsaw", subcommand, "--help"],
            capture_output=True,
            text=True,
            timeout=60,
        )

        assert "--no-network" in result.stdout

    def test_flag_beats_the_repository_config(self, tmp_path, server):
        repo = _materialize("content/external-links", tmp_path, server.port)

        result = run_lint(repo, "--no-network", config=repo / ".skillsaw.yaml")

        assert server.hits == []
        assert RULE_ID not in {v["rule_id"] for v in result["out"]["violations"]}

    def test_flag_beats_an_explicit_rule_flag(self, tmp_path, server):
        """``--rule`` selects which rules run; it does not grant network access."""
        repo = _materialize("content/external-links", tmp_path, server.port)

        run_lint(repo, "--rule", RULE_ID, "--no-network", config=repo / ".skillsaw.yaml")

        assert server.hits == []

    def test_env_var_is_honoured(self, tmp_path, server, monkeypatch):
        repo = _materialize("content/external-links", tmp_path, server.port)
        monkeypatch.setenv("SKILLSAW_NO_NETWORK", "1")

        run_lint(repo, config=repo / ".skillsaw.yaml")

        assert server.hits == []

    @pytest.mark.parametrize("value", ["0", "false", "no", ""])
    def test_env_var_off_values_do_not_gate(self, value, tmp_path, server, monkeypatch):
        repo = _materialize("content/external-links", tmp_path, server.port)
        monkeypatch.setenv("SKILLSAW_NO_NETWORK", value)

        run_lint(repo, config=repo / ".skillsaw.yaml")

        assert server.hits, f"SKILLSAW_NO_NETWORK={value!r} must not gate"

    def test_engaging_the_network_is_announced(self, tmp_path, server):
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

        repo = _materialize("content/external-links", tmp_path, server.port)

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "skillsaw",
                "lint",
                "-c",
                str(repo / ".skillsaw.yaml"),
                str(repo),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

        assert "Network access enabled for" in result.stderr
        assert RULE_ID in result.stderr
        assert "--no-network" in result.stderr
        assert "UserWarning" not in result.stderr  # rendered, not the stock formatter

    def test_no_announcement_when_the_rule_is_not_running(self, tmp_path, server):
        import subprocess
        import sys

        repo = _materialize("content/external-links", tmp_path, server.port, keep_config=False)

        result = subprocess.run(
            [sys.executable, "-m", "skillsaw", "lint", str(repo)],
            capture_output=True,
            text=True,
            timeout=120,
        )

        assert "Network access enabled" not in result.stderr

    def test_gate_is_declarative_not_a_rule_id_list(self):
        """A future network rule inherits the gate by declaring the attribute."""
        from skillsaw.rule import Rule

        assert Rule.requires_network is False
        assert ContentBrokenExternalReferenceRule.requires_network is True

    def test_a_plugin_rule_declaring_the_attribute_is_gated_too(self, tmp_path):
        from skillsaw.rule import Rule, Severity as Sev

        class _NetworkPluginRule(Rule):
            requires_network = True

            @property
            def rule_id(self):
                return "test-network-plugin"

            @property
            def description(self):
                return "test"

            def default_severity(self):
                return Sev.INFO

            def check(self, context):
                raise AssertionError("must not run under --no-network")

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "CLAUDE.md").write_text("# Project\n\nBuild with make.\n", encoding="utf-8")

        linter = Linter(RepositoryContext(repo), LinterConfig.default(), no_network=True)
        linter.rules.append(_NetworkPluginRule())

        linter._apply_network_gate()

        assert "test-network-plugin" not in {r.rule_id for r in linter.rules}


class TestUntrustedConfig:
    """``.skillsaw.yaml`` is untrusted repo content (THREAT_MODEL T13).

    Every option here is repo-controlled, so a hostile or mistyped value
    must degrade to the default — never to something more permissive
    than the default, and never to a hang.
    """

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
        ],
    )
    def test_timeout_is_clamped(self, setting, value, expected, monkeypatch):
        rule = ContentBrokenExternalReferenceRule({"enabled": True, setting: value})
        seen = {}

        def _capture(urls, timeout, budget, concurrency):
            seen.update(timeout=timeout, budget=budget, concurrency=concurrency)
            return {}, 0

        monkeypatch.setattr(rule, "_probe_all", _capture)
        monkeypatch.setattr(rule, "_collect", lambda ctx: {"https://example.com/": []})

        rule.check(None)

        assert seen["timeout"] == pytest.approx(expected)

    @pytest.mark.parametrize(
        "value,expected",
        [
            (-1, 30.0),  # negative must not read as "no cap"
            (float("nan"), 30.0),
            (float("inf"), 30.0),
            (0, 0.0),  # the one documented way to disable the cap
            (10_000, 600.0),
        ],
    )
    def test_budget_is_clamped(self, value, expected, monkeypatch):
        rule = ContentBrokenExternalReferenceRule({"enabled": True, "total-budget": value})
        seen = {}

        def _capture(urls, timeout, budget, concurrency):
            seen["budget"] = budget
            return {}, 0

        monkeypatch.setattr(rule, "_probe_all", _capture)
        monkeypatch.setattr(rule, "_collect", lambda ctx: {"https://example.com/": []})

        rule.check(None)

        assert seen["budget"] == pytest.approx(expected)

    @pytest.mark.parametrize(
        "value,expected",
        [(100_000, 32), (0, 1), (-4, 1), (float("inf"), 8), ("many", 8)],
    )
    def test_concurrency_is_clamped(self, value, expected, monkeypatch):
        rule = ContentBrokenExternalReferenceRule({"enabled": True, "concurrency": value})
        seen = {}

        def _capture(urls, timeout, budget, concurrency):
            seen["concurrency"] = concurrency
            return {}, 0

        monkeypatch.setattr(rule, "_probe_all", _capture)
        monkeypatch.setattr(rule, "_collect", lambda ctx: {"https://example.com/": []})

        rule.check(None)

        assert seen["concurrency"] == expected

    def test_a_string_ignore_does_not_silence_every_url(self, tmp_path, server):
        """``ignore: "https://..."`` is the likeliest YAML mistake here.

        Iterating the string yields single characters, and
        ``url.startswith("h")`` then matched every http(s) URL — the rule
        would report nothing while appearing to run.
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

    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1/x",
            "http://localhost/x",
            "https://sub.localhost/x",
            "http://[::1]/x",
            "http://10.0.0.5/x",
            "http://192.168.1.1/x",
            "http://172.16.0.1/x",
            # The cloud metadata endpoint, the concrete attack in review.
            "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
            # IPv4-mapped IPv6 must not launder a loopback address.
            "http://[::ffff:127.0.0.1]/x",
            "http://0.0.0.0/x",
            "http://[fe80::1]/x",
        ],
    )
    def test_non_public_hosts_are_refused_by_default(self, url):
        rule = ContentBrokenExternalReferenceRule({"enabled": True})

        assert rule._admit(url) is None

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

        violations = _run_rule(repo, {"allow-private-hosts": False})

        assert violations == []
        assert server.hits == []


class TestRedirectTargetsAreVetted:
    """Admission runs on every hop, not only on the authored URL."""

    def test_redirect_into_an_ignored_host_is_not_followed(self, tmp_path, server):
        """Otherwise ``ignore`` is bypassable by any origin that answers 302."""
        rule = ContentBrokenExternalReferenceRule(
            {
                "enabled": True,
                "allow-private-hosts": True,
                "ignore": [f"http://127.0.0.1:{server.port}/relocated"],
            }
        )

        status, checked = rule._probe(f"http://127.0.0.1:{server.port}/redirect-missing", 5.0, None)

        assert server.paths() == ["/redirect-missing"]  # the hop was refused
        assert checked is True
        assert status not in (404, 410)

    def test_redirect_to_a_private_host_is_not_followed(self, server):
        """A public URL must not be able to walk the linter inside."""
        rule = ContentBrokenExternalReferenceRule({"enabled": True})

        assert rule._accepts_hop("http://169.254.169.254/latest/") is False
        assert rule._accepts_hop("https://example.com/ok") is True

    def test_redirect_carrying_userinfo_is_not_followed(self, server):
        rule = ContentBrokenExternalReferenceRule({"enabled": True})

        assert rule._accepts_hop("https://user:token@example.com/x") is False


class TestHeadIsNeverEnoughToConvict:
    """Regression: PR #521's first real-repo run flagged live pages.

    Two of the reported findings were servers that answer 404 to HEAD and
    serve the resource on GET — nvlpubs.nist.gov's copy of NIST SP
    800-53r5, and an azure.microsoft.com product page. RFC 9110 says HEAD
    must answer as GET would minus the body; real servers disagree, so a
    candidate violation is confirmed with GET before it is reported.
    """

    def test_head_404_with_get_200_is_not_reported(self, tmp_path, server):
        repo = _materialize("content/external-links", tmp_path, server.port)

        violations = _run_rule(repo)

        assert "/head-404-get-200" not in "\n".join(_messages(violations))
        assert _methods_by_path(server)["/head-404-get-200"] == ["HEAD", "GET"]

    def test_head_410_with_get_200_is_not_reported(self, tmp_path, server):
        repo = _materialize("content/external-links", tmp_path, server.port)

        violations = _run_rule(repo)

        assert "/head-410-get-200" not in "\n".join(_messages(violations))
        assert _methods_by_path(server)["/head-410-get-200"] == ["HEAD", "GET"]

    def test_a_confirmed_404_is_still_reported(self, tmp_path, server):
        """The fix must not silence links that really are gone."""
        repo = _materialize("content/external-links", tmp_path, server.port)

        violations = _run_rule(repo)

        assert any("/missing" in m for m in _messages(violations))
        assert _methods_by_path(server)["/missing"] == ["HEAD", "GET"]

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

    def test_exhausted_budget_emits_one_info_notice(self, tmp_path, server):
        repo = _materialize("content/external-links-slow", tmp_path, server.port)

        # One worker, a one-second budget, two URLs that never answer: the
        # first burns the budget, the second is never requested.
        violations = _run_rule(repo, {"timeout": 5, "total-budget": 1, "concurrency": 1})

        assert len(violations) == 1
        notice = violations[0]
        assert notice.severity == Severity.INFO
        assert "left unchecked" in notice.message
        assert "network budget" in notice.message
        assert len(server.paths()) == 1

    def test_budget_notice_message_is_stable(self, tmp_path, server):
        """The notice must be baselinable, so no count may reach its message.

        It has no file, so baseline identity falls through to hashing
        rule_id + message. A count that moves with runner latency would
        re-fingerprint the notice on every run — impossible to baseline,
        and a new finding every time under ``fail-on: info``.
        """
        repo = _materialize("content/external-links-slow", tmp_path, server.port)

        first = _run_rule(repo, {"timeout": 5, "total-budget": 1, "concurrency": 1})
        second = _run_rule(repo, {"timeout": 5, "total-budget": 0.5, "concurrency": 1})

        assert first[0].message == second[0].message
        assert not any(char.isdigit() for char in first[0].message)
        assert first[0].fingerprint_discriminator == "network-budget-exhausted"

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

    def test_a_bare_setting_enables_the_rule(self, tmp_path, server):
        """For a disabled-by-default rule, ANY non-`enabled` key turns it on.

        `config.rule_enabled_reason` returns "configured in config
        (overrides disabled-by-default)" for a lone `ignore:` or
        `severity:`. The rule doc states it; nothing pinned it, and it is
        the single most hermeticity-relevant behaviour in the feature.
        """
        repo = _materialize("content/external-links", tmp_path, server.port, keep_config=False)
        (repo / ".skillsaw.yaml").write_text(
            'version: "99.0.0"\n' "rules:\n" f"  {RULE_ID}:\n" "    allow-private-hosts: true\n",
            encoding="utf-8",
        )

        result = run_lint(repo, config=repo / ".skillsaw.yaml")

        assert server.hits, "a bare setting must be enough to start requesting"
        assert RULE_ID in {v["rule_id"] for v in result["out"]["violations"]}

    def test_explicit_enabled_false_keeps_it_off_despite_settings(self, tmp_path, server):
        """The documented escape hatch: settings without activation."""
        repo = _materialize("content/external-links", tmp_path, server.port, keep_config=False)
        (repo / ".skillsaw.yaml").write_text(
            'version: "99.0.0"\n'
            "rules:\n"
            f"  {RULE_ID}:\n"
            "    enabled: false\n"
            "    allow-private-hosts: true\n"
            "    timeout: 5\n",
            encoding="utf-8",
        )

        run_lint(repo, config=repo / ".skillsaw.yaml")

        assert server.hits == []

    def test_rule_flag_enables_the_disabled_rule(self, tmp_path, server):
        """`--rule` is the documented entry point; nothing else pins it.

        A future change making `--rule` a pure filter over already-enabled
        rules would break every invocation the docs recommend while every
        other test stayed green.
        """
        repo = _materialize("content/external-links", tmp_path, server.port, keep_config=False)
        (repo / ".skillsaw.yaml").write_text(
            'version: "99.0.0"\n'
            "rules:\n"
            f"  {RULE_ID}:\n"
            "    enabled: false\n"
            "    allow-private-hosts: true\n",
            encoding="utf-8",
        )

        result = run_lint(repo, "--rule", RULE_ID, config=repo / ".skillsaw.yaml")

        assert server.hits, "--rule must force-enable a disabled-by-default rule"
        assert RULE_ID in {v["rule_id"] for v in result["out"]["violations"]}

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

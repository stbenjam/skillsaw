"""Skills over MCP (SEP-2640): ``skillsaw lint --mcp-server`` and its client."""

import io
import json
import os
import shlex
import shutil
import sys
import tempfile
import time
from pathlib import Path

import pytest

from skillsaw import mcp_client
from skillsaw import mcp_skills_pull as pull_module
from skillsaw.formats import mcp_skills
from tests import mcp_skills_fake_server as fake
from tests.cli_runner import run_cli

FIXTURES = Path(__file__).parent / "fixtures" / "mcp-skills"
SERVED = FIXTURES / "served"
FAKE_SERVER = Path(__file__).parent / "mcp_skills_fake_server.py"


def fake_command(*args):
    return f'"{sys.executable}" "{FAKE_SERVER}" "{SERVED}" ' + " ".join(args)


def pull(tmp_path, server, *args):
    """``skillsaw pull`` *server* (a URL or a stdio command line) into ``snapshot/``.

    The server is named "fake" in an MCP config, so its skills land in
    ``snapshot/fake``.
    """
    if server.startswith(("http://", "https://")):
        entry = {"url": server}
    else:
        command, *rest = shlex.split(server)
        entry = {"command": command, "args": rest}
    config = tmp_path / "fake-mcp.json"
    config.write_text(json.dumps({"mcpServers": {"fake": entry}}))
    out = tmp_path / "snapshot"
    result = run_cli(["pull", "--mcp-config", config, "-o", out] + list(args))
    return result, out


# ── Snapshot paths ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "uri",
    [
        "skill://D:/outside/SKILL.md",
        "skill://docs/a%3Ab/SKILL.md",
        "skill://docs/..%20/SKILL.md",
        "skill://docs/trailing./SKILL.md",
        "skill://docs/%2e%2e/SKILL.md",
        "skill://docs//SKILL.md",
        "skill://docs/a%5Cb/SKILL.md",
        "skill://con/SKILL.md",
        "skill://docs/NUL.md",
        "skill://docs/com1.txt",
        "skill://docs/a%2Ab.md",
        "skill://docs/a%7Cb.md",
        "skill://docs/a%22b.md",
    ],
)
def test_unsafe_uri_segments_have_no_local_path(uri):
    # Drive letters, alternate data streams, device names and trailing dots
    # mean something else on Windows; refusing them everywhere keeps a
    # snapshot portable.
    assert mcp_skills.local_parts(uri) is None


def test_safe_uri_segments_map_under_the_server():
    assert mcp_skills.local_parts("skill://acme/billing/refunds/SKILL.md") == (
        "acme",
        "billing",
        "refunds",
        "SKILL.md",
    )
    assert mcp_skills.local_parts("github://o/r/x%20y/SKILL.md") == (
        "_github",
        "o",
        "r",
        "x y",
        "SKILL.md",
    )


@pytest.mark.parametrize(
    "url,described",
    [
        ("https://mcp.example.com/api/s3cret/mcp?key=x", "https://mcp.example.com"),
        ("https://user:pw@mcp.example.com:8443/mcp", "https://mcp.example.com:8443"),
        ("http://[::1]:8080/mcp", "http://[::1]:8080"),
    ],
    ids=["path-key", "user-info", "ipv6"],
)
def test_a_target_is_described_by_its_origin(url, described):
    # Some services carry an API key in the path; the description is printed
    # and recorded in the snapshot.
    assert pull_module.ServerTarget(label="x", kind="http", url=url).describe() == described


@pytest.mark.parametrize(
    "line,windows,expected",
    [
        ('npx -y "@acme/skills server"', False, ["npx", "-y", "@acme/skills server"]),
        (
            r'C:\tools\server.exe --root "C:\Program Files\data"',
            True,
            [r"C:\tools\server.exe", "--root", r"C:\Program Files\data"],
        ),
    ],
    ids=["posix", "windows"],
)
def test_command_lines_split_by_platform_rules(line, windows, expected):
    assert pull_module.split_command(line, windows=windows) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        ("Bearer ${MCP_SET}", "Bearer set"),
        ("${MCP_SET:-fallback}", "set"),
        ("${MCP_UNSET:-fallback}", "fallback"),
        ("${MCP_UNSET}", "${MCP_UNSET}"),
    ],
)
def test_config_values_expand_like_mcp_clients(monkeypatch, value, expected):
    monkeypatch.setenv("MCP_SET", "set")
    monkeypatch.delenv("MCP_UNSET", raising=False)
    assert pull_module._expand(value) == expected


# ── Fetching and linting ─────────────────────────────────────────


class TestPull:
    def test_stdio_pull_writes_a_lintable_snapshot(self, tmp_path):
        result, out = pull(tmp_path, fake_command())
        assert result.returncode == 0, result.stderr
        snapshot = json.loads((out / mcp_skills.SNAPSHOT_FILENAME).read_text())
        server = snapshot["servers"][0]
        assert server["protocolVersion"] == "2026-07-28"
        assert server["errors"] == []
        assert sorted(entry["uri"] for entry in server["skills"]) == [
            "skill://acme/billing/refunds/SKILL.md",
            "skill://pdf-processing/SKILL.md",
            "skill://release-notes/SKILL.md",
            "skill://reports/SKILL.md",
            "skill://reports/daily/SKILL.md",
        ]
        for path in SERVED.rglob("*"):
            if path.is_file():
                rel = path.relative_to(SERVED)
                assert (out / "fake" / rel).read_bytes() == path.read_bytes()
        assert "problem(s) with the servers" not in result.stderr
        # Served skills are Agent Skills: the ordinary rules read them.
        lint = run_cli(["lint", out, "--format", "json", "--no-progress"])
        assert any(
            v["rule_id"] == "security-hidden-instructions"
            and Path(v["file_path"]).as_posix() == "fake/release-notes/SKILL.md"
            for v in json.loads(lint.stdout)["violations"]
        )

    def test_legacy_stdio_server(self, tmp_path):
        result, out = pull(tmp_path, fake_command("--legacy"))
        assert result.returncode == 0, result.stderr
        server = json.loads((out / mcp_skills.SNAPSHOT_FILENAME).read_text())["servers"][0]
        assert server["protocolVersion"] == "2025-11-25"
        assert len(server["skills"]) == 5

    def test_served_content_that_disagrees_with_its_entry_fails_the_run(self, tmp_path):
        command = fake_command(
            "--tamper", "policy.md", "--lie-frontmatter", "pdf-processing", "--dynamic", "reports"
        )
        result, out = pull(tmp_path, command)
        assert result.returncode == 1
        problems = [(e.get("uri"), e["message"].split(".")[0]) for e in pulled(out)["errors"]]
        assert problems == [
            (
                "skill://acme/billing/refunds/SKILL.md",
                "1 file(s) do not match the digest or size the server advertised: "
                "references/policy",
            ),
            (
                "skill://pdf-processing/SKILL.md",
                "the advertised frontmatter differs from the served SKILL",
            ),
        ]
        assert "2 problem(s) with the servers" in result.stderr
        # A dynamic skill has no digests to check; its files were found
        # through directory reads and are linted like the rest.
        assert (out / "fake" / "reports" / "daily" / "SKILL.md").is_file()
        # The tampered bytes are kept, so the lint reads what was served.
        assert (
            out / "fake" / "acme" / "billing" / "refunds" / "references" / "policy.md"
        ).is_file()

    def test_hostile_uris_stay_inside_the_snapshot(self, tmp_path):
        evil = {
            "uri": "skill://../escape/SKILL.md",
            "frontmatter": {"name": "escape", "description": "x"},
            "resources": [
                {"uri": "skill://../escape/SKILL.md", "digest": "sha256:" + "0" * 64, "size": 1}
            ],
        }
        sneaky = {
            "uri": "skill://sneaky/SKILL.md",
            "frontmatter": {"name": "sneaky", "description": "Sneaky. Use when testing."},
            "resources": [
                {"uri": "skill://sneaky/SKILL.md", "digest": "sha256:" + "0" * 64, "size": 3},
                {
                    "uri": "skill://sneaky/%2e%2e/%2e%2e/owned.md",
                    "digest": "sha256:" + "0" * 64,
                    "size": 3,
                },
            ],
        }
        options = fake.Options(
            extra_entries=[evil, sneaky],
            extra_files={
                "skill://sneaky/SKILL.md": b"---\nname: sneaky\ndescription: Sneaky. Use when testing.\n---\n",
                "skill://sneaky/%2e%2e/%2e%2e/owned.md": b"pwn",
            },
        )
        httpd = fake.start_http(fake.Server(fake.Catalog(SERVED, options)))
        try:
            url = f"http://127.0.0.1:{httpd.server_address[1]}/mcp"
            result, out = pull(tmp_path, url)
        finally:
            httpd.shutdown()
        assert result.returncode == 1, result.stderr
        assert not (tmp_path / "escape").exists()
        assert not (tmp_path / "owned.md").exists()
        assert not (out / "owned.md").exists()
        messages = [e["message"] for e in pulled(out)["errors"]]
        assert any("does not name a skill's SKILL.md" in m for m in messages)
        assert any("refused: the URI cannot be stored safely" in m for m in messages)

    @pytest.mark.parametrize(
        "options,version",
        [
            (fake.Options(), "2026-07-28"),
            (fake.Options(legacy=True), "2025-11-25"),
            (fake.Options(sse=True), "2026-07-28"),
            (fake.Options(legacy=True, sse=True), "2025-11-25"),
        ],
        ids=["modern", "legacy", "modern-sse", "legacy-sse"],
    )
    def test_http_pull(self, tmp_path, options, version):
        httpd = fake.start_http(fake.Server(fake.Catalog(SERVED, options)))
        try:
            url = f"http://127.0.0.1:{httpd.server_address[1]}/mcp"
            result, out = pull(tmp_path, url)
        finally:
            httpd.shutdown()
        server = json.loads((out / mcp_skills.SNAPSHOT_FILENAME).read_text())["servers"][0]
        assert server["protocolVersion"] == version
        assert server["target"] == url.removesuffix("/mcp")  # the origin only
        assert server["errors"] == []
        assert result.returncode == 0, result.stderr

    def test_redirects_are_not_followed(self, tmp_path):
        # Following a redirect would replay the user's headers to another host.
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading

        seen = []

        class Target(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                seen.append(self.headers.get("Authorization"))
                self.send_response(500)
                self.end_headers()

            do_GET = do_POST

        target = ThreadingHTTPServer(("127.0.0.1", 0), Target)

        class Redirect(Target):
            def do_POST(self):
                self.send_response(307)
                self.send_header("Location", f"http://127.0.0.1:{target.server_address[1]}/")
                self.end_headers()

        redirect = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
        for server in (target, redirect):
            threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            url = f"http://127.0.0.1:{redirect.server_address[1]}/mcp"
            result = run_cli(
                ["lint", "--mcp-server", url, "--mcp-header", "Authorization: Bearer secret"]
            )
        finally:
            target.shutdown()
            redirect.shutdown()
        assert seen == []
        assert "redirect refused" in result.stderr
        assert result.returncode == 1

    def test_server_without_skills_is_not_a_problem(self, tmp_path):
        httpd = fake.start_http(fake.Server(fake.Catalog(SERVED, fake.Options(no_extension=True))))
        try:
            result, out = pull(tmp_path, f"http://127.0.0.1:{httpd.server_address[1]}/mcp")
        finally:
            httpd.shutdown()
        # Most MCP servers serve no skills; there is just nothing to lint.
        assert result.returncode == 0, result.stderr
        assert "fake: serves no skills" in result.stderr
        assert pulled(out)["errors"] == [] and pulled(out)["skills"] == []

    def test_linting_a_server_without_skills_passes_quietly(self, tmp_path):
        httpd = fake.start_http(fake.Server(fake.Catalog(SERVED, fake.Options(no_extension=True))))
        try:
            url = f"http://127.0.0.1:{httpd.server_address[1]}/mcp"
            result = run_cli(["lint", "--mcp-server", url, "--no-progress"])
        finally:
            httpd.shutdown()
        assert result.returncode == 0, result.stderr
        assert "serves no skills" in result.stderr
        # The fetched directory is skillsaw's own, not a repository to recognize.
        assert "recognized repository" not in result.stderr

    def test_unreachable_server_is_reported(self, tmp_path):
        result, out = pull(tmp_path, "http://127.0.0.1:9/mcp")
        assert result.returncode == 1
        [error] = pulled(out)["errors"]
        assert "could not reach server" in error["message"]
        assert "1 problem(s) with the servers" in result.stderr

    def test_servers_from_mcp_config(self, tmp_path):
        config = tmp_path / ".mcp.json"
        config.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "Docs Server": {
                            "command": sys.executable,
                            "args": [str(FAKE_SERVER), "${SKILLS_DIR}"],
                        },
                        "events": {"type": "sse", "url": "http://127.0.0.1:9/sse"},
                        "half-written": {},
                        "listed-headers": {
                            "url": "https://mcp.example.com/mcp",
                            "headers": ["Authorization: x"],
                        },
                    }
                }
            )
        )
        env = {**os.environ, "SKILLS_DIR": str(SERVED)}
        out = tmp_path / "snapshot"
        result = run_cli(
            ["pull", "--mcp-config", ".mcp.json", "-o", out],
            env=env,
            cwd=tmp_path,
        )
        assert result.returncode == 0, result.stderr
        assert "docs-server: 5 skill(s)" in result.stderr
        assert (out / "docs-server" / "pdf-processing" / "SKILL.md").is_file()
        # Entries skillsaw cannot fetch from are skipped, not fatal.
        assert "Skipping events: it uses the retired HTTP+SSE transport" in result.stderr
        assert "Skipping half-written: it has neither a 'url' nor a 'command'" in result.stderr
        assert "Skipping listed-headers: its 'headers' is not an object" in result.stderr
        config.write_text(json.dumps({"mcpServers": {"half-written": {}}}))
        result = run_cli(["pull", "--mcp-config", ".mcp.json", "-o", out], cwd=tmp_path)
        assert result.returncode == 1
        assert "lists no server skillsaw can fetch from" in result.stderr

    def test_pull_replaces_only_a_snapshot(self, tmp_path):
        out = tmp_path / "snapshot"
        out.mkdir()
        (out / "notes.txt").write_text("keep me\n")
        result, _ = pull(tmp_path, fake_command())
        assert result.returncode == 1 and "not a skillsaw snapshot" in result.stderr
        # A snapshot file does not make the rest of the directory replaceable.
        (out / mcp_skills.SNAPSHOT_FILENAME).write_text('{"servers": [{"label": "fake"}]}')
        result, _ = pull(tmp_path, fake_command())
        assert result.returncode == 1 and "not a skillsaw snapshot" in result.stderr
        assert (out / "notes.txt").read_text() == "keep me\n"

        shutil.rmtree(out)
        assert pull(tmp_path, fake_command())[0].returncode == 0
        (out / "fake" / "stale.md").write_text("from an older pull\n")
        result, out = pull(tmp_path, fake_command())
        assert result.returncode == 0, result.stderr
        assert not (out / "fake" / "stale.md").exists()
        assert pulled(out)["errors"] == []

    def test_served_skills_lint_with_the_local_config(self, tmp_path, monkeypatch):
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        monkeypatch.setattr(tempfile, "tempdir", str(scratch))
        (tmp_path / ".skillsaw.yaml").write_text(
            "rules:\n  security-hidden-instructions:\n    severity: error\n"
        )
        result = run_cli(
            ["lint", "--mcp-server", fake_command(), "--format", "json", "--no-progress"],
            cwd=tmp_path,
        )
        [hidden] = [
            v
            for v in json.loads(result.stdout)["violations"]
            if v["rule_id"] == "security-hidden-instructions"
        ]
        # The stdio server is named for its script, and the configuration where
        # skillsaw ran applies to what it serves.
        assert hidden["file_path"] == "mcp_skills_fake_server.py/release-notes/SKILL.md"
        assert hidden["severity"] == "error"
        assert result.returncode == 1
        # The fetched skills lived in a temporary directory, now gone.
        assert list(scratch.iterdir()) == []

    def test_a_header_goes_to_one_url_only(self, tmp_path):
        # One header set for several hosts would give each one the others' token.
        result = run_cli(
            [
                "lint",
                "--mcp-server",
                "https://a.example/mcp",
                "--mcp-server",
                "https://b.example/mcp",
                "--mcp-header",
                "Authorization: Bearer secret",
            ]
        )
        assert result.returncode == 1
        assert "--mcp-header applies to a single --mcp-server URL" in result.stderr

    @pytest.mark.parametrize("command", ["lint", "tree"])
    @pytest.mark.parametrize(
        "args,message",
        [
            (["--mcp-header", "Authorization: Bearer x"], "needs a --mcp-server URL"),
            (["--mcp-server", "https://a.example/mcp"], "take the place of a path"),
        ],
    )
    def test_server_options_are_used_on_their_own(self, tmp_path, command, args, message):
        result = run_cli([command, str(tmp_path), *args])
        assert result.returncode == 2
        assert message in result.stderr

    def test_tree_shows_what_servers_serve(self, tmp_path, monkeypatch):
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        monkeypatch.setattr(tempfile, "tempdir", str(scratch))
        result = run_cli(["tree", "--mcp-server", fake_command("--tamper", "policy.md")])
        assert result.stdout.startswith("mcp-skills/"), result.stdout
        assert "Fetching skills from " in result.stderr and " into " not in result.stderr
        assert "release-notes/ [skill]" in result.stdout
        # The tree still prints; the server's problem fails the run after it.
        assert "1 problem(s) with the servers" in result.stderr
        assert result.returncode == 1
        assert list(scratch.iterdir()) == []

    def test_server_behind_auth(self, tmp_path):
        server, httpd, url = http_server(fake.Options(require_token="s3cret"))
        try:
            refused = run_cli(["lint", "--mcp-server", url, "--format", "json"])
            calls = list(server.calls)
            out = tmp_path / "snapshot"
            run_cli(
                [
                    "pull",
                    "--mcp-server",
                    url,
                    "--mcp-header",
                    "Authorization: Bearer s3cret",
                    "-o",
                    out,
                ]
            )
        finally:
            httpd.shutdown()
        # A 401 means credentials, not a legacy server: no fallback handshake.
        assert calls == ["server/discover"]
        assert refused.returncode == 1
        assert "the server requires authorization (HTTP 401)" in refused.stderr
        assert "--mcp-header" in refused.stderr
        assert pulled(out)["errors"] == [] and len(pulled(out)["skills"]) == 5

    def test_malformed_entries_are_server_problems(self, tmp_path):
        nameless = {"uri": "skill://a/SKILL.md", "frontmatter": {"name": "b"}}
        stray = {
            "uri": "skill://c/SKILL.md",
            "frontmatter": {"name": "c", "description": "C."},
            "resources": [{"uri": "skill://d/x.md", "digest": "md5:1"}],
        }
        server, httpd, url = http_server(fake.Options(extra_entries=[nameless, stray]))
        try:
            result, out = pull(tmp_path, url)
        finally:
            httpd.shutdown()
        assert result.returncode == 1
        problems = {e["uri"]: e["message"] for e in pulled(out)["errors"]}
        assert problems["skill://a/SKILL.md"] == (
            "malformed entry: frontmatter name 'b' does not equal the URI's final segment 'a'; "
            "frontmatter has no description; 'resources' is missing or invalid"
        )
        assert problems["skill://c/SKILL.md"] == (
            "malformed entry: its resources omit SKILL.md itself; 1 resource(s) lack a valid "
            "sha256 digest; 1 resource(s) lack a byte size; 1 resource(s) lie outside the skill"
        )

    def test_pull_names_where_each_server_goes(self, tmp_path):
        out = tmp_path / "mcp-skills"
        result = run_cli(["pull", "--mcp-server", fake_command(), "-o", out])
        assert result.returncode == 0, result.stderr
        # A pull lints nothing, so it has no report.
        assert result.stdout == ""
        assert f"into {out / 'mcp_skills_fake_server.py'}/" in result.stderr

    @pytest.mark.parametrize(
        "args,message",
        [
            (["-o", "out"], "pull needs --mcp-server or --mcp-config"),
            (["--mcp-server", "https://a.example/mcp"], "the following arguments are required"),
        ],
    )
    def test_pull_needs_a_server_and_a_directory(self, tmp_path, args, message):
        result = run_cli(["pull", *args], cwd=tmp_path)
        assert result.returncode == 2
        assert message in result.stderr

    def test_config_is_never_found_beside_the_scratch_directory(self, tmp_path, monkeypatch):
        # Anyone can write to the scratch directory's ancestors (/tmp); a
        # config planted there must not steer the run.
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        monkeypatch.setattr(tempfile, "tempdir", str(scratch))
        (scratch / ".skillsaw.yaml").write_text(
            "rules:\n  security-hidden-instructions:\n    enabled: false\n"
        )
        work = tmp_path / "work"
        work.mkdir()
        result = run_cli(
            ["lint", "--mcp-server", fake_command(), "--format", "json", "--no-progress"],
            cwd=work,
        )
        rules = {v["rule_id"] for v in json.loads(result.stdout)["violations"]}
        assert "security-hidden-instructions" in rules

    def test_the_local_baseline_does_not_apply_to_served_skills(self, tmp_path):
        from skillsaw import __version__

        work = tmp_path / "work"
        shutil.copytree(SERVED, work)
        (work / ".skillsaw.yaml").write_text(f'version: "{__version__}"\n')
        assert run_cli(["baseline", work]).returncode == 0
        assert (work / ".skillsaw-baseline.json").is_file()
        result = run_cli(["lint", "--mcp-server", fake_command(), "--no-progress"], cwd=work)
        # The baseline describes the repository, so none of it is stale here.
        assert "stale" not in result.stdout + result.stderr
        assert "security-hidden-instructions" in result.stdout

    def test_yaml_typed_frontmatter_matches_its_json_spelling(self, tmp_path):
        # PyYAML reads 2024-01-01 as a date and yes as true; a server that
        # parsed the file another way advertises both as text.
        uri = "skill://dated/SKILL.md"
        skill_md = (
            b"---\nname: dated\ndescription: Dated notes. Use when testing.\n"
            b"updated: 2024-01-01\nreleased: 2024-02-03\nbeta: yes\nmode: 0755\n---\n\n# Dated\n"
        )
        entry = {
            "uri": uri,
            "frontmatter": {
                "name": "dated",
                "description": "Dated notes. Use when testing.",
                "updated": "2024-01-01",
                "released": "2024-02-03T00:00:00.000Z",  # a JavaScript Date
                "beta": "yes",
                "mode": "0755",
            },
            "resources": [
                {"uri": uri, "digest": mcp_skills.sha256_digest(skill_md), "size": len(skill_md)}
            ],
        }
        server, httpd, url = http_server(
            fake.Options(extra_entries=[entry], extra_files={uri: skill_md})
        )
        try:
            result, out = pull(tmp_path, url)
        finally:
            httpd.shutdown()
        assert result.returncode == 0, result.stderr
        assert pulled(out)["errors"] == []

    @pytest.mark.parametrize(
        "files,size",
        [(mcp_skills.MAX_RESOURCES_PER_SKILL + 1, 1), (1, mcp_skills.MAX_BYTES_PER_SKILL + 1)],
        ids=["files", "bytes"],
    )
    def test_skills_beyond_the_host_limits_are_not_fetched(self, tmp_path, files, size):
        uri = "skill://huge/SKILL.md"
        digest = "sha256:" + "0" * 64
        resources = [{"uri": uri, "digest": digest, "size": size}] + [
            {"uri": f"skill://huge/f{n}.md", "digest": digest, "size": 1} for n in range(files - 1)
        ]
        frontmatter = {"name": "huge", "description": "Huge. Use when testing."}
        entry = {"uri": uri, "frontmatter": frontmatter, "resources": resources}
        server, httpd, url = http_server(fake.Options(extra_entries=[entry]))
        try:
            result, out = pull(tmp_path, url)
        finally:
            httpd.shutdown()
        assert result.returncode == 1
        [error] = [e for e in pulled(out)["errors"] if e.get("uri") == uri]
        assert "beyond the 512-file / 16 MiB limits hosts must accept" in error["message"]
        assert not (out / "fake" / "huge").exists()

    def test_a_typed_value_is_still_compared(self, tmp_path):
        uri = "skill://counted/SKILL.md"
        skill_md = (
            b"---\nname: counted\ndescription: Counted. Use when testing.\nrevision: 123\n---\n"
        )
        frontmatter = {"name": "counted", "description": "Counted. Use when testing."}
        entry = {
            "uri": uri,
            "frontmatter": {**frontmatter, "revision": "other"},
            "resources": [
                {"uri": uri, "digest": mcp_skills.sha256_digest(skill_md), "size": len(skill_md)}
            ],
        }
        server, httpd, url = http_server(
            fake.Options(extra_entries=[entry], extra_files={uri: skill_md})
        )
        try:
            result, out = pull(tmp_path, url)
        finally:
            httpd.shutdown()
        assert result.returncode == 1
        [error] = [e for e in pulled(out)["errors"] if e.get("uri") == uri]
        assert error["message"].startswith("the advertised frontmatter differs")

    @pytest.mark.parametrize(
        "served,advertised",
        [("2024-99-99", "2024-01-01"), ("2024-01-01", "2024-99-99")],
        ids=["served", "advertised"],
    )
    def test_an_impossible_date_is_a_mismatch_not_a_crash(self, tmp_path, served, advertised):
        # PyYAML raises a bare ValueError constructing 2024-99-99.
        uri = "skill://dated/SKILL.md"
        skill_md = (
            "---\nname: dated\ndescription: Dated. Use when testing.\n" f"released: {served}\n---\n"
        ).encode()
        frontmatter = {"name": "dated", "description": "Dated. Use when testing."}
        entry = {
            "uri": uri,
            "frontmatter": {**frontmatter, "released": advertised},
            "resources": [
                {"uri": uri, "digest": mcp_skills.sha256_digest(skill_md), "size": len(skill_md)}
            ],
        }
        server, httpd, url = http_server(
            fake.Options(extra_entries=[entry], extra_files={uri: skill_md})
        )
        try:
            result, out = pull(tmp_path, url)
        finally:
            httpd.shutdown()
        assert "Traceback" not in result.stderr
        assert result.returncode == 1
        [error] = [e for e in pulled(out)["errors"] if e.get("uri") == uri]
        assert error["message"].startswith("the advertised frontmatter differs")

    def test_a_server_that_stops_answering_is_not_waited_on_per_file(self, tmp_path):
        server, httpd, url = http_server(fake.Options(stall_reads_seconds=3))
        try:
            result, out = pull(tmp_path, url, "--mcp-timeout", "0.5")
        finally:
            httpd.shutdown()
        assert result.returncode == 1
        # One timeout stops the server, rather than one per remaining file.
        assert server.calls.count("resources/read") == 1
        assert any(
            e["message"].startswith("stopped: timed out after 0.5s waiting for resources/read")
            for e in pulled(out)["errors"]
        )

    def test_a_malformed_cursor_is_a_problem_not_the_end(self, tmp_path):
        server, httpd, url = http_server(fake.Options(malformed_cursor=True))
        try:
            result, out = pull(tmp_path, url)
        finally:
            httpd.shutdown()
        assert result.returncode == 1
        assert any("nextCursor that is not a string" in e["message"] for e in pulled(out)["errors"])

    @pytest.mark.parametrize(
        "entry,message",
        [(5, "listed an entry that is not an object"), ({"uri": 1}, "carry no string uri")],
        ids=["not-an-object", "no-uri"],
    )
    def test_a_malformed_directory_entry_is_a_problem(self, tmp_path, entry, message):
        # Skipping it could leave a file out of a listing called complete.
        options = fake.Options(dynamic=["pdf-processing"], malformed_directory_entry=entry)
        server, httpd, url = http_server(options)
        try:
            result, out = pull(tmp_path, url)
        finally:
            httpd.shutdown()
        assert result.returncode == 1
        assert any(message in e["message"] for e in pulled(out)["errors"])

    def test_paths_differing_only_in_normalization_are_refused(self, tmp_path):
        # macOS treats NFC é and NFD é as one name.
        root = "skill://accented"
        files = {
            f"{root}/SKILL.md": b"---\nname: accented\ndescription: Accented. Use when testing.\n---\n",
            f"{root}/caf%C3%A9.md": b"composed\n",
            f"{root}/cafe%CC%81.md": b"decomposed\n",
        }
        resources = [
            {"uri": uri, "digest": mcp_skills.sha256_digest(data), "size": len(data)}
            for uri, data in files.items()
        ]
        frontmatter = {"name": "accented", "description": "Accented. Use when testing."}
        entry = {"uri": f"{root}/SKILL.md", "frontmatter": frontmatter, "resources": resources}
        server, httpd, url = http_server(fake.Options(extra_entries=[entry], extra_files=files))
        try:
            result, out = pull(tmp_path, url)
        finally:
            httpd.shutdown()
        assert result.returncode == 1
        [error] = [e for e in pulled(out)["errors"] if e.get("uri") == f"{root}/cafe%CC%81.md"]
        assert error["message"] == (
            f"refused: on macOS and Windows its path is the same as {root}/caf%C3%A9.md"
        )

    def test_paths_differing_only_in_case_are_refused(self, tmp_path):
        # macOS and Windows would merge them, so the snapshot could not be checked out.
        root = "skill://cased"
        files = {
            f"{root}/SKILL.md": b"---\nname: cased\ndescription: Cased. Use when testing.\n---\n",
            f"{root}/README.md": b"upper\n",
            f"{root}/readme.md": b"lower\n",
        }
        resources = [
            {"uri": uri, "digest": mcp_skills.sha256_digest(data), "size": len(data)}
            for uri, data in files.items()
        ]
        frontmatter = {"name": "cased", "description": "Cased. Use when testing."}
        entry = {"uri": f"{root}/SKILL.md", "frontmatter": frontmatter, "resources": resources}
        server, httpd, url = http_server(fake.Options(extra_entries=[entry], extra_files=files))
        try:
            result, out = pull(tmp_path, url)
        finally:
            httpd.shutdown()
        assert result.returncode == 1
        [error] = [e for e in pulled(out)["errors"] if e.get("uri") == f"{root}/readme.md"]
        assert error["message"] == (
            f"refused: on macOS and Windows its path is the same as {root}/README.md"
        )
        assert not (out / "fake" / "cased" / "readme.md").exists()

    @pytest.mark.skipif(not os.path.exists("/dev/zero"), reason="needs /dev/zero")
    def test_a_snapshot_record_symlink_is_not_read(self, tmp_path):
        # Following it to /dev/zero would read without end.
        out = tmp_path / "snapshot"
        (out / "docs").mkdir(parents=True)
        os.symlink("/dev/zero", out / mcp_skills.SNAPSHOT_FILENAME)
        result, _ = pull(tmp_path, fake_command())
        assert result.returncode == 1 and "not a skillsaw snapshot" in result.stderr
        assert (out / "docs").is_dir()

    def test_a_launch_value_the_system_refuses_is_a_server_problem(self, tmp_path):
        config = tmp_path / "mcp.json"
        entry = {"command": sys.executable, "args": ["-c", "pass\u0000"]}
        config.write_text(json.dumps({"mcpServers": {"nul": entry}}))
        out = tmp_path / "out"
        result = run_cli(["pull", "--mcp-config", config, "-o", out])
        assert result.returncode == 1
        assert "Traceback" not in result.stderr
        [error] = pulled(out)["errors"]
        assert "hold a character the system refuses" in error["message"]

    def test_a_pull_cut_short_can_be_replaced(self, tmp_path, monkeypatch):
        out = tmp_path / "snapshot"
        pull_module.prepare_output(out)
        target = pull_module.ServerTarget(label="docs", kind="http", url="http://x/")

        def interrupted(self, timeout):
            self.server_dir.mkdir(parents=True)
            raise KeyboardInterrupt

        monkeypatch.setattr(pull_module._ServerPull, "run", interrupted)
        with pytest.raises(KeyboardInterrupt):
            pull_module.pull([target], out)
        # The record written before the fetch still names what it made.
        pull_module.prepare_output(out)
        assert list(out.iterdir()) == []

    def test_a_quoted_served_value_is_compared_as_text(self, tmp_path):
        # Quoted, "yes" is text to every YAML parser, never true.
        uri = "skill://quoted/SKILL.md"
        skill_md = b'---\nname: quoted\ndescription: Quoted. Use when testing.\nbeta: "yes"\n---\n'
        frontmatter = {"name": "quoted", "description": "Quoted. Use when testing."}
        entry = {
            "uri": uri,
            "frontmatter": {**frontmatter, "beta": True},
            "resources": [
                {"uri": uri, "digest": mcp_skills.sha256_digest(skill_md), "size": len(skill_md)}
            ],
        }
        server, httpd, url = http_server(
            fake.Options(extra_entries=[entry], extra_files={uri: skill_md})
        )
        try:
            result, out = pull(tmp_path, url)
        finally:
            httpd.shutdown()
        assert result.returncode == 1
        [error] = [e for e in pulled(out)["errors"] if e.get("uri") == uri]
        assert error["message"].startswith("the advertised frontmatter differs")

    def test_an_unencodable_host_does_not_stop_the_snapshot(self, tmp_path):
        config = tmp_path / "mcp.json"
        config.write_text(json.dumps({"servers": {"odd": {"url": "http://exa\ud800mple.com/mcp"}}}))
        out = tmp_path / "out"
        result = run_cli(["pull", "--mcp-config", config, "-o", out])
        assert result.returncode == 1
        assert "Traceback" not in result.stderr
        assert pulled(out)["errors"]

    def test_a_planted_snapshot_cannot_clear_a_directory(self, tmp_path):
        out = tmp_path / "snapshot"
        (out / ".git").mkdir(parents=True)
        (out / "README.md").write_text("keep me\n")
        (out / mcp_skills.SNAPSHOT_FILENAME).write_text(
            json.dumps({"servers": [{"label": ".git"}, {"label": "README.md"}]})
        )
        result, _ = pull(tmp_path, fake_command())
        assert result.returncode == 1 and "not a skillsaw snapshot" in result.stderr
        assert (out / ".git").is_dir() and (out / "README.md").read_text() == "keep me\n"
        # A malformed record is no snapshot at all.
        (out / mcp_skills.SNAPSHOT_FILENAME).write_text('{"servers": 5}')
        result, _ = pull(tmp_path, fake_command())
        assert result.returncode == 1 and "not a skillsaw snapshot" in result.stderr
        assert "Traceback" not in result.stderr

    def test_a_configured_working_directory_is_used(self, tmp_path):
        server_dir = tmp_path / "servers" / "docs"
        server_dir.mkdir(parents=True)
        shutil.copy(FAKE_SERVER, server_dir / "server.py")
        config = tmp_path / "mcp.json"
        entry = {
            "command": sys.executable,
            "args": ["server.py", str(SERVED)],
            "cwd": "servers/docs",
        }
        config.write_text(json.dumps({"mcpServers": {"docs": entry}}))
        result = run_cli(["pull", "--mcp-config", config, "-o", tmp_path / "out"])
        assert result.returncode == 0, result.stderr
        assert "docs: 5 skill(s)" in result.stderr

    def test_config_headers_expand_variables_and_stay_out_of_the_snapshot(self, tmp_path):
        server, httpd, url = http_server(fake.Options(require_token="s3cret"))
        config = tmp_path / "mcp.json"
        headers = {"Authorization": "Bearer ${MCP_TOKEN}"}
        config.write_text(json.dumps({"servers": {"private": {"url": url, "headers": headers}}}))
        out = tmp_path / "out"
        try:
            result = run_cli(
                ["pull", "--mcp-config", config, "-o", out],
                env={**os.environ, "MCP_TOKEN": "s3cret"},
            )
        finally:
            httpd.shutdown()
        assert result.returncode == 0, result.stderr
        assert len(pulled(out)["skills"]) == 5
        assert "s3cret" not in (out / mcp_skills.SNAPSHOT_FILENAME).read_text()
        assert "s3cret" not in result.stderr

    @pytest.mark.parametrize("command", ["lint", "tree"])
    def test_without_a_path_the_current_directory_is_used(self, tmp_path, command):
        work = tmp_path / "skills"
        shutil.copytree(SERVED, work)
        result = run_cli([command], cwd=work)
        assert "release-notes" in result.stdout, result.stderr
        assert "Fetching" not in result.stderr  # plain runs never reach a server

    def test_a_header_with_a_line_break_is_refused_unquoted(self, tmp_path):
        # A trailing newline is a common way for a secret to arrive from CI.
        config = tmp_path / "mcp.json"
        headers = {"Authorization": "Bearer ${MCP_TOKEN}"}
        entry = {"url": "https://mcp.example.com/mcp", "headers": headers}
        config.write_text(json.dumps({"servers": {"private": entry}}))
        result = run_cli(
            ["pull", "--mcp-config", config, "-o", tmp_path / "out"],
            env={**os.environ, "MCP_TOKEN": "s3cret\n"},
        )
        assert result.returncode == 1
        assert "Authorization header's value contains a line break" in result.stderr
        assert "s3cret" not in result.stderr

    @pytest.mark.parametrize(
        "spec,message",
        [
            ("Authorization Bearer s3cret", "must look like 'Name: value'"),
            (": Bearer s3cret", "must look like 'Name: value'"),
            ("Authorization Bearer s3cret: x", "a header name is not a valid HTTP token"),
        ],
    )
    def test_a_malformed_header_is_refused_unquoted(self, spec, message):
        result = run_cli(
            ["lint", "--mcp-server", "https://mcp.example.com/mcp", "--mcp-header", spec]
        )
        assert result.returncode == 1
        assert message in result.stderr
        assert "s3cret" not in result.stderr

    def test_an_unparseable_command_line_is_refused_unquoted(self):
        result = run_cli(["lint", "--mcp-server", 'server --token s3cret "unclosed'])
        assert result.returncode == 1
        assert "cannot parse a --mcp-server command line" in result.stderr
        assert "s3cret" not in result.stderr

    @pytest.mark.parametrize(
        "field,value,message",
        [
            ("args", "--safe-mode", "its 'args' is not an array"),
            ("env", ["SAFE_MODE=1"], "its 'env' is not an object"),
            ("args", ["--port", None], "its 'args' holds a value that is not a string"),
            ("cwd", 0, "its 'cwd' is not a string"),
        ],
    )
    def test_config_launch_fields_of_the_wrong_shape_are_refused(
        self, tmp_path, field, value, message
    ):
        # Dropping them would start a different server than the config names.
        config = tmp_path / "mcp.json"
        entry = {"command": sys.executable, field: value}
        config.write_text(json.dumps({"mcpServers": {"misshapen": entry}}))
        result = run_cli(["pull", "--mcp-config", config, "-o", tmp_path / "out"])
        assert result.returncode == 1
        assert f"Skipping misshapen: {message}" in result.stderr

    def test_jsonc_configs_and_odd_entries(self, tmp_path):
        # VS Code and Cursor configs carry comments and trailing commas; an
        # entry that is not an object is reported rather than dropped.
        config = tmp_path / "mcp.json"
        docs = json.dumps({"command": sys.executable, "args": [str(FAKE_SERVER), str(SERVED)]})
        config.write_text(
            '{\n  // the docs server\n  "servers": {\n'
            f'    "docs": {docs},\n    "broken": "oops",\n'
            "  },\n}\n"
        )
        result = run_cli(["pull", "--mcp-config", config, "-o", tmp_path / "out"])
        assert result.returncode == 0, result.stderr
        assert "docs: 5 skill(s)" in result.stderr
        assert "Skipping broken: it is not an object" in result.stderr

    def test_a_bare_server_map_is_a_config(self, tmp_path):
        # A plugin's .mcp.json may be the server map itself.
        config = tmp_path / ".mcp.json"
        entry = {"command": sys.executable, "args": [str(FAKE_SERVER), str(SERVED)]}
        config.write_text(json.dumps({"docs": entry}))
        result = run_cli(["pull", "--mcp-config", config, "-o", tmp_path / "out"])
        assert result.returncode == 0, result.stderr
        assert "docs: 5 skill(s)" in result.stderr

    def test_a_disabled_server_is_never_started(self, tmp_path):
        marker = tmp_path / "started"
        config = tmp_path / "mcp.json"
        started = {"command": sys.executable, "args": ["-c", f"open({str(marker)!r}, 'w')"]}
        config.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "off": {**started, "disabled": True},
                        "docs": {
                            "command": sys.executable,
                            "args": [str(FAKE_SERVER), str(SERVED)],
                        },
                    }
                }
            )
        )
        result = run_cli(["pull", "--mcp-config", config, "-o", tmp_path / "out"])
        assert result.returncode == 0, result.stderr
        assert "Skipping off: it is disabled" in result.stderr
        assert not marker.exists()

    def test_a_config_nested_too_deeply_is_an_error(self, tmp_path, parser_gives_up_on_nesting):
        config = tmp_path / "mcp.json"
        config.write_text("[" * 64 + "]" * 64)
        result = run_cli(["pull", "--mcp-config", config, "-o", tmp_path / "out"])
        assert result.returncode == 1
        assert "Nesting too deep to parse" in result.stderr
        assert "Traceback" not in result.stderr

    def test_credentials_in_a_url_are_refused_unquoted(self):
        result = run_cli(["lint", "--mcp-server", "https://user:s3cret@mcp.example.com/mcp"])
        assert result.returncode == 1
        assert "the URL carries credentials" in result.stderr
        assert "s3cret" not in result.stderr

    def test_served_bytes_are_capped_when_sizes_are_not_advertised(self, tmp_path, monkeypatch):
        # A dynamic skill advertises no sizes, so only the bytes served bound it.
        monkeypatch.setattr(mcp_skills, "MAX_BYTES_PER_SKILL", 600)
        server, httpd, url = http_server(fake.Options(dynamic=["pdf-processing"]))
        try:
            result, out = pull(tmp_path, url)
        finally:
            httpd.shutdown()
        assert result.returncode == 1
        messages = [
            e["message"]
            for e in pulled(out)["errors"]
            if e.get("uri", "").startswith("skill://pdf-processing/")
        ]
        assert "stopped: the skill's files exceed 16 MiB" in messages

    def test_files_another_skill_fetched_count_toward_this_one(self, tmp_path, monkeypatch):
        # Listed first, reports/daily fetches its SKILL.md; the dynamic parent's
        # walk reaches the same file, and it must count there too.
        monkeypatch.setattr(mcp_skills, "MAX_BYTES_PER_SKILL", 500)
        server, httpd, url = http_server(fake.Options(dynamic=["reports"], reverse_listing=True))
        try:
            result, out = pull(tmp_path, url)
        finally:
            httpd.shutdown()
        assert result.returncode == 1
        assert any(
            e["message"] == "stopped: the skill's files exceed 16 MiB"
            and e.get("uri", "").startswith("skill://reports/")
            for e in pulled(out)["errors"]
        )

    def test_contents_for_another_uri_are_refused(self, tmp_path):
        # A dynamic skill advertises no digest that would catch the swap.
        invoice = "skill://pdf-processing/templates/invoice.md"
        options = fake.Options(
            dynamic=["pdf-processing"],
            misattributed_reads={invoice: "skill://release-notes/SKILL.md"},
        )
        server, httpd, url = http_server(options)
        try:
            result, out = pull(tmp_path, url)
        finally:
            httpd.shutdown()
        assert result.returncode == 1
        [error] = [e for e in pulled(out)["errors"] if e.get("uri") == invoice]
        assert "returned contents for a different URI" in error["message"]
        assert not (out / "fake" / "pdf-processing" / "templates" / "invoice.md").exists()

    def test_a_deeply_nested_entry_is_refused_not_fatal(self, tmp_path):
        nested: dict = {}
        node = nested
        for _ in range(600):
            node["a"] = {}
            node = node["a"]
        frontmatter = {"name": "deep", "description": "Deep. Use when testing.", "metadata": nested}
        entry = {"uri": "skill://deep/SKILL.md", "frontmatter": frontmatter, "resources": []}
        server, httpd, url = http_server(fake.Options(extra_entries=[entry]))
        try:
            result, out = pull(tmp_path, url)
        finally:
            httpd.shutdown()
        assert result.returncode == 1
        assert "Traceback" not in result.stderr
        assert any("nests too deeply" in e["message"] for e in pulled(out)["errors"])
        assert len(pulled(out)["skills"]) == 5  # the server's other skills are kept


# ── Client bounds ────────────────────────────────────────────────


def http_server(options):
    server = fake.Server(fake.Catalog(SERVED, options))
    httpd = fake.start_http(server)
    return server, httpd, f"http://127.0.0.1:{httpd.server_address[1]}/mcp"


def pulled(out):
    return json.loads((out / mcp_skills.SNAPSHOT_FILENAME).read_text())["servers"][0]


@pytest.fixture
def parser_gives_up_on_nesting(monkeypatch):
    """Make ``json.loads`` raise ``RecursionError`` on deeply nested arrays.

    How deep CPython can parse depends on the platform's stack: 3.14 on a
    large stack parses nesting that raises ``RecursionError`` elsewhere, so
    the tests simulate the parser giving up rather than rely on either.
    """
    real = json.loads

    def loads(data, *args, **kwargs):
        head = data[:4] if isinstance(data, (bytes, bytearray)) else str(data[:4]).encode()
        if bytes(head) == b"[[[[":
            raise RecursionError("maximum recursion depth exceeded while decoding a JSON array")
        return real(data, *args, **kwargs)

    monkeypatch.setattr(json, "loads", loads)


def python_server(source):
    """A stdio "server" running *source*, for transport-level misbehavior."""
    return mcp_client.StdioTransport([sys.executable, "-c", source])


@pytest.mark.skipif(os.name != "posix", reason="signal handling differs off POSIX")
class TestStdioShutdown:
    def test_server_that_ignores_eof_and_sigterm_is_killed(self, monkeypatch):
        monkeypatch.setattr(mcp_client, "_EXIT_GRACE", 0.2)
        transport = python_server(
            "import signal, time\n"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "time.sleep(120)\n"
        )
        with pytest.raises(mcp_client.McpError, match="timed out"):
            transport.send({"jsonrpc": "2.0", "id": 1, "method": "ping"}, headers={}, timeout=0.05)
        start = time.monotonic()
        transport.close()
        assert time.monotonic() - start < 3
        assert transport._process.poll() is not None

    def test_grandchild_holding_stdout_does_not_block_close(self, monkeypatch):
        # A launcher (npx, uvx) whose child outlives it keeps the pipe open.
        monkeypatch.setattr(mcp_client, "_EXIT_GRACE", 0.2)
        transport = python_server(
            "import subprocess, sys\n"
            "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        )
        start = time.monotonic()
        transport.close()
        assert time.monotonic() - start < 3
        assert not transport._reader.is_alive()

    def test_deeply_nested_json_is_a_server_error(self, parser_gives_up_on_nesting):
        transport = python_server(
            "import sys\n"
            "sys.stdin.readline()\n"
            "print('[' * 64 + ']' * 64, flush=True)\n"
            "sys.stdin.read()\n"
        )
        try:
            with pytest.raises(mcp_client.McpError, match="nested too deeply"):
                transport.send(
                    {"jsonrpc": "2.0", "id": 1, "method": "skills/list"}, headers={}, timeout=10
                )
        finally:
            transport.close()

    def test_backlog_is_bounded_in_bytes(self, monkeypatch):
        # The byte budget is charged as messages are taken, so what waits in
        # the backlog needs its own bound.
        monkeypatch.setattr(mcp_client, "MAX_MESSAGE_BYTES", 4096)
        transport = python_server(
            "import sys\n"
            "for _ in range(50):\n"
            "    print('x' * 1000, flush=True)\n"
            "sys.stdin.read()\n"
        )
        try:
            deadline = time.monotonic() + 5
            while transport._messages.qsize() < 4 and time.monotonic() < deadline:
                time.sleep(0.05)
            time.sleep(0.3)  # time to overfill, were the bound missing
            assert transport._messages.qsize() == 4  # 1,001-byte lines
            assert transport._backlog_bytes <= 4096
        finally:
            transport.close()

    def test_a_line_is_read_only_up_to_the_request_limit(self):
        # A small byte budget must also bound what the reader takes in.
        transport = python_server(
            "import sys\n"
            "sys.stdin.readline()\n"
            "print('x' * 1000000, flush=True)\n"
            "sys.stdin.read()\n"
        )
        try:
            with pytest.raises(mcp_client.McpSizeError):
                transport.send(
                    {"jsonrpc": "2.0", "id": 1, "method": "skills/list"},
                    headers={},
                    timeout=10,
                    limit=1000,
                )
        finally:
            transport.close()
        # A read already waiting may finish its chunk; nothing more is taken in.
        assert transport.bytes_received <= mcp_client._READ_CHUNK + 1

    def test_an_error_code_that_is_not_an_integer_is_no_crash(self):
        transport = python_server(
            "import json, sys\n"
            "for line in sys.stdin:\n"
            "    request = json.loads(line)\n"
            "    if 'id' in request:\n"
            "        error = {'code': [1], 'message': 'odd'}\n"
            "        reply = {'jsonrpc': '2.0', 'id': request['id'], 'error': error}\n"
            "        print(json.dumps(reply), flush=True)\n"
        )
        session = mcp_client.McpSession(transport, timeout=10)
        try:
            with pytest.raises(mcp_client.McpError):
                session.connect()
        finally:
            session.close()

    def test_an_unsupported_legacy_version_is_refused(self):
        transport = python_server(
            "import json, sys\n"
            "for line in sys.stdin:\n"
            "    request = json.loads(line)\n"
            "    if 'id' not in request:\n"
            "        continue\n"
            "    if request['method'] == 'initialize':\n"
            "        result = {'protocolVersion': '2099-01-01', 'capabilities': {},\n"
            "                  'serverInfo': {'name': 'future', 'version': '1'}}\n"
            "        reply = {'jsonrpc': '2.0', 'id': request['id'], 'result': result}\n"
            "    else:\n"
            "        error = {'code': -32601, 'message': 'Method not found'}\n"
            "        reply = {'jsonrpc': '2.0', 'id': request['id'], 'error': error}\n"
            "    print(json.dumps(reply), flush=True)\n"
        )
        session = mcp_client.McpSession(transport, timeout=10)
        try:
            with pytest.raises(mcp_client.McpError, match="2099-01-01"):
                session.connect()
        finally:
            session.close()

    def test_server_ping_is_answered(self):
        # A legacy server may check the connection mid-request.
        transport = python_server(
            "import json, sys\n"
            "request = json.loads(sys.stdin.readline())\n"
            "print(json.dumps({'jsonrpc': '2.0', 'id': 'hc', 'method': 'ping'}), flush=True)\n"
            "pong = json.loads(sys.stdin.readline())\n"
            "print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': pong}), flush=True)\n"
        )
        try:
            response = transport.send(
                {"jsonrpc": "2.0", "id": 1, "method": "skills/list"}, headers={}, timeout=10
            )
        finally:
            transport.close()
        assert response["result"] == {"jsonrpc": "2.0", "id": "hc", "result": {}}

    def test_server_that_stops_reading_cannot_block_a_write(self, monkeypatch):
        # The refusal of a server's own request echoes its id; a megabyte
        # id overfills the pipe of a server that never reads its input.
        monkeypatch.setattr(mcp_client, "_EXIT_GRACE", 0.2)
        transport = python_server(
            "import json, sys, time\n"
            "request = {'jsonrpc': '2.0', 'id': 'x' * (1 << 20), 'method': 'roots/list'}\n"
            "sys.stdout.write(json.dumps(request) + '\\n')\n"
            "sys.stdout.flush()\n"
            "time.sleep(120)\n"
        )
        ping = {"jsonrpc": "2.0", "id": 1, "method": "skills/list"}
        start = time.monotonic()
        with pytest.raises(mcp_client.McpError, match="timed out after 0.3s"):
            transport.send(ping, headers={}, timeout=0.3)
        assert time.monotonic() - start < 1.5
        with pytest.raises(mcp_client.McpError, match="stopped reading its input"):
            transport.send(ping, headers={}, timeout=0.3)
        start = time.monotonic()
        transport.close()
        assert time.monotonic() - start < 3
        assert transport._process.poll() is not None

    def test_lines_that_are_not_json_count_against_the_limit(self, monkeypatch):
        monkeypatch.setattr(mcp_client, "_EXIT_GRACE", 0.2)
        transport = python_server(
            "import sys\n"
            "sys.stdin.readline()\n"
            "sys.stdout.write('x' * 1000000 + '\\n')\n"
            'sys.stdout.write(\'{"jsonrpc": "2.0", "id": 1, "result": {}}\\n\')\n'
            "sys.stdout.flush()\n"
            "sys.stdin.readline()\n"
        )
        try:
            with pytest.raises(mcp_client.McpSizeError):
                transport.send(
                    {"jsonrpc": "2.0", "id": 1, "method": "skills/list"},
                    headers={},
                    timeout=10,
                    limit=4096,
                )
            # The noise counted, and reading stopped soon past the limit.
            assert 4096 < transport.bytes_received <= mcp_client._READ_CHUNK + 1
        finally:
            transport.close()

    def test_notifications_do_not_extend_the_deadline(self, monkeypatch):
        monkeypatch.setattr(mcp_client, "_EXIT_GRACE", 0.2)
        transport = python_server(
            "import sys, time\n"
            "while True:\n"
            '    sys.stdout.write(\'{"jsonrpc": "2.0", "method": "notifications/progress"}\\n\')\n'
            "    sys.stdout.flush()\n"
            "    time.sleep(0.01)\n"
        )
        try:
            start = time.monotonic()
            with pytest.raises(mcp_client.McpError, match="timed out after 0.3s"):
                transport.send(
                    {"jsonrpc": "2.0", "id": 1, "method": "skills/list"}, headers={}, timeout=0.3
                )
            assert time.monotonic() - start < 1.5
        finally:
            transport.close()


class _DripServer:
    """A raw HTTP server that answers every request one byte at a time."""

    def __init__(self, reply, interval=0.05):
        import socket
        import threading

        self.reply, self.interval = reply, interval
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen()
        self.url = f"http://127.0.0.1:{self.sock.getsockname()[1]}/mcp"
        self.stop = threading.Event()
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while not self.stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                try:
                    conn.recv(65536)
                    for byte in self.reply:
                        if self.stop.is_set():
                            return
                        conn.sendall(bytes([byte]))
                        time.sleep(self.interval)
                except OSError:
                    continue

    def close(self):
        self.stop.set()
        self.sock.close()


class _Drip:
    """A response body that never ends a line."""

    def __init__(self, chunk=b"x" * 512):
        self.chunk = chunk
        self.served = 0

    def read1(self, n):
        piece = self.chunk[:n]
        self.served += len(piece)
        return piece


class TestBoundedReads:
    def test_sse_line_without_end_stops_at_the_limit(self):
        stream = _Drip()
        events = mcp_client._sse_messages(
            stream, deadline=time.monotonic() + 30, timeout=30, method="x", limit=4096
        )
        with pytest.raises(mcp_client.McpSizeError):
            list(events)
        assert stream.served <= 4097

    @pytest.mark.parametrize("eol", [b"\n", b"\r\n", b"\r"], ids=["lf", "crlf", "cr"])
    @pytest.mark.parametrize("size", [1, 2, 7, 4096])
    def test_sse_events_split_across_reads(self, eol, size):
        # Any SSE line ending, a leading BOM, comments, a field without a
        # colon, and a final event the stream does not terminate.
        lines = [
            b'\xef\xbb\xbfdata: {"a":',
            b": comment",
            b"event: message",
            b"data:  1}",
            b"",
            b"data",
            b"",
            b"data: not json",
            b"",
            b'data: {"b": 2}',
        ]
        body = eol.join(lines)
        pieces = [body[i : i + size] for i in range(0, len(body), size)]

        class Stream:
            def read1(self, n):
                return pieces.pop(0) if pieces else b""

        events = mcp_client._sse_messages(
            Stream(), deadline=time.monotonic() + 30, timeout=30, method="x", limit=1 << 20
        )
        assert [message for message, _ in events] == [{"a": 1}, {"b": 2}]

    def test_stalled_http_body_is_a_server_error(self, tmp_path):
        server, httpd, url = http_server(fake.Options(stall_body_seconds=3))
        try:
            start = time.monotonic()
            result, out = pull(tmp_path, url, "--mcp-timeout", "0.5")
        finally:
            httpd.shutdown()
        assert time.monotonic() - start < 2.5
        assert result.returncode == 1, result.stderr
        assert "Traceback" not in result.stderr
        [error] = pulled(out)["errors"]
        assert "timed out after 0.5s waiting for server/discover" in error["message"]

    def test_status_line_counts_against_the_budget(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading

        reason = "x" * 60000

        class Verbose(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                body = json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": {}}).encode()
                self.send_response(200, reason)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Verbose)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            transport = mcp_client.HttpTransport(f"http://127.0.0.1:{httpd.server_address[1]}/mcp")
            transport.send({"jsonrpc": "2.0", "id": 1, "method": "ping"}, headers={}, timeout=5)
        finally:
            httpd.shutdown()
        assert transport.bytes_received > len(reason)

    def test_name_resolution_shares_the_deadline(self, monkeypatch):
        monkeypatch.setattr(mcp_client.socket, "getaddrinfo", lambda *a, **k: time.sleep(5))
        transport = mcp_client.HttpTransport("http://stalled-resolver.invalid/mcp")
        start = time.monotonic()
        with pytest.raises(mcp_client.McpError):
            transport.send({"jsonrpc": "2.0", "id": 1, "method": "ping"}, headers={}, timeout=0.3)
        assert time.monotonic() - start < 1.5

    def test_a_failure_at_the_deadline_is_a_timeout(self, monkeypatch):
        # The socket timeout can land before the watchdog's timer thread runs.
        monkeypatch.setattr(mcp_client._Watchdog, "_fire", lambda self: None)

        def stalled(self, message, headers, watchdog, timeout, limit):
            time.sleep(timeout + 0.1)
            raise mcp_client.McpError("could not reach server: timed out")

        monkeypatch.setattr(mcp_client.HttpTransport, "_exchange", stalled)
        transport = mcp_client.HttpTransport("http://127.0.0.1:9/mcp")
        with pytest.raises(mcp_client.McpTimeoutError):
            transport.send({"jsonrpc": "2.0", "id": 1, "method": "ping"}, headers={}, timeout=0.2)

    def test_invalid_request_errors_do_not_quote_header_values(self):
        server, httpd, url = http_server(fake.Options())
        try:
            transport = mcp_client.HttpTransport(url)
            with pytest.raises(mcp_client.McpError) as raised:
                transport.send(
                    {"jsonrpc": "2.0", "id": 1, "method": "skills/list"},
                    headers={"Authorization": "Bearer s3cret\n"},
                    timeout=5,
                )
        finally:
            httpd.shutdown()
        assert "not valid HTTP" in str(raised.value)
        assert "s3cret" not in str(raised.value)

    def test_deeply_nested_http_json_is_a_server_problem(
        self, tmp_path, parser_gives_up_on_nesting
    ):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading

        body = b"[" * 64 + b"]" * 64

        class Deep(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Deep)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            result, out = pull(tmp_path, f"http://127.0.0.1:{httpd.server_address[1]}/mcp")
        finally:
            httpd.shutdown()
        assert result.returncode == 1, result.stderr
        assert "Traceback" not in result.stderr
        assert "nested too deeply" in pulled(out)["errors"][0]["message"]

    @pytest.mark.parametrize(
        "reply",
        [
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nX-Pad: " + b"a" * 200,
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
            b"Transfer-Encoding: chunked\r\n\r\n1;" + b"x" * 200,
        ],
        ids=["headers", "chunk-size"],
    )
    def test_dripped_framing_does_not_outlast_the_deadline(self, reply):
        # Each byte arrives well inside the socket timeout, so only a
        # deadline on the whole exchange stops it.
        server = _DripServer(reply)
        try:
            transport = mcp_client.HttpTransport(server.url)
            start = time.monotonic()
            with pytest.raises(mcp_client.McpError, match="timed out after 0.3s"):
                transport.send(
                    {"jsonrpc": "2.0", "id": 1, "method": "skills/list"}, headers={}, timeout=0.3
                )
            assert time.monotonic() - start < 1.5
        finally:
            server.close()

    def test_cr_ended_event_dispatches_without_another_read(self):
        # The server keeps the stream open after a whole event; waiting
        # for the next read to pair the final CR would stall the request.
        pieces = [b'data: {"a": 1}\r\r']

        class OpenStream:
            def read1(self, n):
                if not pieces:
                    raise AssertionError("waited on an open stream for a sent event")
                return pieces.pop(0)

        events = mcp_client._sse_messages(
            OpenStream(), deadline=time.monotonic() + 30, timeout=30, method="x", limit=1 << 20
        )
        assert next(events)[0] == {"a": 1}

    def test_long_line_parses_in_linear_time(self):
        # A large resource arrives as one data line over many reads; each
        # read must not rescan the bytes before it.
        payload = b'data: {"text": "' + b"x" * (16 << 20) + b'"}\n\n'
        events = mcp_client._sse_messages(
            io.BytesIO(payload),
            deadline=time.monotonic() + 5,
            timeout=5,
            method="resources/read",
            limit=len(payload),
        )
        assert len(next(events)[0]["text"]) == 16 << 20

    @pytest.mark.skipif(not sys.platform.startswith("linux"), reason="relies on Linux backlog")
    def test_every_connect_attempt_shares_the_deadline(self, monkeypatch):
        # A full accept backlog leaves each connect hanging; a host that
        # resolves to four such addresses must still fail at the deadline.
        import socket

        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(0)
        address = listener.getsockname()
        fillers = []
        for _ in range(8):
            filler = socket.socket()
            filler.setblocking(False)
            try:
                filler.connect(address)
            except BlockingIOError:
                pass
            fillers.append(filler)
        time.sleep(0.1)
        monkeypatch.setattr(
            mcp_client.socket,
            "getaddrinfo",
            lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", address)] * 4,
        )
        try:
            transport = mcp_client.HttpTransport(f"http://example.invalid:{address[1]}/mcp")
            start = time.monotonic()
            with pytest.raises(mcp_client.McpError):
                transport.send(
                    {"jsonrpc": "2.0", "id": 1, "method": "skills/list"}, headers={}, timeout=0.3
                )
            assert time.monotonic() - start < 1.0
        finally:
            for sock in [listener, *fillers]:
                sock.close()

    def test_unsupported_address_family_falls_through_to_the_next(self, tmp_path, monkeypatch):
        # A host without IPv6 cannot create a socket for "::1"; like
        # socket.create_connection, the client should try the next address.
        import socket

        server, httpd, url = http_server(fake.Options())
        address = ("127.0.0.1", httpd.server_address[1])
        unsupported = (255, socket.SOCK_STREAM, 6, "", ("::1", address[1], 0, 0))
        supported = (socket.AF_INET, socket.SOCK_STREAM, 6, "", address)
        monkeypatch.setattr(
            mcp_client.socket, "getaddrinfo", lambda *a, **k: [unsupported, supported]
        )
        try:
            result, out = pull(tmp_path, url)
        finally:
            httpd.shutdown()
        assert result.returncode == 0, result.stderr
        assert pulled(out)["errors"] == []

    def test_malformed_retry_after_falls_back_to_doubling(self):
        import email.message
        import urllib.error

        headers = email.message.Message()
        headers["Retry-After"] = "\u00b2"
        busy = urllib.error.HTTPError("http://x/", 429, "busy", headers, None)
        assert mcp_client._busy_delay(busy, 1, time.monotonic() + 30) == 2.0

    def test_timeout_must_be_positive(self, tmp_path):
        result = run_cli(["lint", "--mcp-server", "http://127.0.0.1:9/", "--mcp-timeout", "0"])
        assert result.returncode == 2
        assert "--mcp-timeout" in result.stderr


class TestPullBudgets:
    def test_listing_stops_at_the_skill_budget(self, tmp_path):
        server, httpd, url = http_server(fake.Options(endless_list=True))
        try:
            result, out = pull(tmp_path, url, "--mcp-max-skills", "3")
        finally:
            httpd.shutdown()
        assert result.returncode == 1, result.stderr
        assert server.calls.count("skills/list") == 2
        record = pulled(out)
        assert len(record["skills"]) == 3
        assert any("lists more than 3 skills" in e["message"] for e in record["errors"])

    def test_spent_byte_budget_stops_the_server(self, tmp_path):
        server, httpd, url = http_server(fake.Options())
        try:
            result, out = pull(tmp_path, url, "--mcp-max-bytes", "6000")
        finally:
            httpd.shutdown()
        assert result.returncode == 1, result.stderr
        errors = [e["message"] for e in pulled(out)["errors"]]
        assert errors == [
            "stopped: the byte budget of 6000 bytes was reached; "
            "later skills and files were not fetched"
        ]
        files = sum(1 for p in SERVED.rglob("*") if p.is_file())
        reads = server.calls.count("resources/read")
        assert 0 < reads < files
        # The request that ran out of budget is the last one sent.
        assert server.calls[-1] == "resources/read"

    def test_failed_responses_count_against_the_budget(self, tmp_path):
        server, httpd, url = http_server(fake.Options(error_body_bytes=4096))
        try:
            result, out = pull(tmp_path, url, "--mcp-max-bytes", "20000")
        finally:
            httpd.shutdown()
        assert result.returncode == 1, result.stderr
        errors = [e["message"] for e in pulled(out)["errors"]]
        assert errors[-1].startswith("stopped: the byte budget of 20000 bytes was reached")
        assert server.calls.count("resources/read") <= 20000 // 4096 + 1

    def test_initialized_notification_counts_against_the_budget(self, tmp_path):
        server, httpd, url = http_server(fake.Options(legacy=True, notification_error_bytes=100000))
        try:
            result, out = pull(tmp_path, url, "--mcp-max-bytes", "4096")
        finally:
            httpd.shutdown()
        errors = [e["message"] for e in pulled(out)["errors"]]
        assert errors == [
            "stopped: the byte budget of 4096 bytes was reached; "
            "later skills and files were not fetched"
        ]
        assert "skills/list" not in server.calls

    def test_directory_walk_is_bounded(self, tmp_path):
        server, httpd, url = http_server(
            fake.Options(dynamic=["pdf-processing"], fan_out_directories=True)
        )
        try:
            result, out = pull(tmp_path, url)
        finally:
            httpd.shutdown()
        assert result.returncode == 1, result.stderr
        assert server.calls.count("resources/directory/read") == pull_module.MAX_DIRECTORY_REQUESTS
        errors = [e for e in pulled(out)["errors"] if "directory walk" in e["message"]]
        assert [e["uri"] for e in errors] == ["skill://pdf-processing"]


class TestBusyServer:
    def test_rate_limited_requests_are_retried(self, tmp_path):
        server, httpd, url = http_server(fake.Options(busy_first=2))
        try:
            result, out = pull(tmp_path, url)
        finally:
            httpd.shutdown()
        assert result.returncode == 0, result.stderr
        assert pulled(out)["errors"] == []

    def test_a_file_that_cannot_be_read_is_not_called_tampered(self, tmp_path):
        uri = "skill://pdf-processing/templates/invoice.md"
        server, httpd, url = http_server(fake.Options(busy_uris=[uri]))
        try:
            result, out = pull(tmp_path, url)
        finally:
            httpd.shutdown()
        assert result.returncode == 1
        assert pulled(out)["errors"] == [
            {"message": "read failed: HTTP 429 from server", "uri": uri}
        ]


class _Listing:
    """A session stub: each directory lists *width* files, and *depth*
    directories nest below the skill root."""

    def __init__(self, width, depth):
        self.width, self.depth = width, depth
        self.requests = 0

    def read_directory(self, uri, *, max_pages, max_entries):
        self.requests += 1
        children = [
            {"uri": f"{uri}/f{n}.md", "mimeType": "text/markdown"} for n in range(self.width)
        ]
        if uri.count("/sub") < self.depth:
            children.append({"uri": f"{uri}/sub", "mimeType": "inode/directory"})
        return children[:max_entries], len(children) <= max_entries


class TestDynamicWalkLimits:
    def walk(self, tmp_path, width, depth=1):
        target = pull_module.ServerTarget(label="fake", kind="http", url="http://x/")
        puller = pull_module._ServerPull(target, tmp_path, max_skills=1, max_bytes=1 << 20)
        listing = _Listing(width, depth)
        files = puller._directory_files(listing, "skill://s", "skill://s/SKILL.md")
        return files, [e["message"] for e in puller.record["errors"]]

    @pytest.mark.parametrize("width", [511, 600])
    def test_reaching_the_file_limit_is_reported(self, tmp_path, width):
        # 511 files fill the limit with SKILL.md while "sub" is still
        # unread; 600 overflow it outright. Neither may pass silently.
        files, errors = self.walk(tmp_path, width)
        assert len(files) == mcp_skills.MAX_RESOURCES_PER_SKILL
        assert len(errors) == 1 and "may be incomplete" in errors[0]

    def test_a_walk_within_bounds_is_complete(self, tmp_path):
        files, errors = self.walk(tmp_path, 3, depth=2)
        assert len(files) == 1 + 3 * 3
        assert errors == []

    def test_nesting_past_the_depth_bound_is_reported(self, tmp_path):
        files, errors = self.walk(tmp_path, 3, depth=100)
        assert len(files) == 1 + 3 * pull_module.MAX_DIRECTORY_DEPTH
        assert len(errors) == 1 and "may be incomplete" in errors[0]


class TestUnicode:
    def test_unpaired_surrogates_are_reported_not_fatal(self, tmp_path):
        bad = {
            "uri": "skill://bad/SKILL.md",
            "frontmatter": {"name": "bad", "description": "Bad \ud800 text."},
            "resources": [],
        }
        uri = "skill://pdf-processing/templates/invoice.md"
        server, httpd, url = http_server(
            fake.Options(extra_entries=[bad], text_overrides={uri: "broken \ud800 text"})
        )
        try:
            result, out = pull(tmp_path, url)
        finally:
            httpd.shutdown()
        assert not list(out.glob(".*partial"))
        messages = [e["message"] for e in pulled(out)["errors"]]
        assert any("cannot be recorded" in m and "not valid Unicode" in m for m in messages)
        assert "read failed: resources/read returned text that is not valid Unicode" in messages
        assert result.returncode == 1


class TestLabels:
    @pytest.mark.parametrize(
        "command,label",
        [
            (["python3", "-c", 'token="s3cret"; serve()'], "python3"),
            (["node", "-e", "serve('s3cret')"], "node"),
            (["python3", "-m", "acme.server"], "acme.server"),
        ],
    )
    def test_inline_code_never_names_a_server(self, command, label):
        assert pull_module._command_label(command) == label

    def test_the_snapshot_file_name_is_reserved(self):
        targets = [
            pull_module.ServerTarget(
                label=mcp_skills.SNAPSHOT_FILENAME, kind="http", url="http://x/"
            )
        ]
        pull_module.unique_labels(targets)
        assert targets[0].label != mcp_skills.SNAPSHOT_FILENAME

    def test_repeated_labels_avoid_every_label_in_use(self):
        targets = [
            pull_module.ServerTarget(label=label, kind="http", url="http://x/")
            for label in ("docs", "docs", "docs-2", "docs")
        ]
        pull_module.unique_labels(targets)
        assert [t.label for t in targets] == ["docs", "docs-3", "docs-2", "docs-4"]

    def test_long_labels_keep_their_suffix(self):
        long = mcp_skills.sanitize_label("x" * 100)
        targets = [
            pull_module.ServerTarget(label=long, kind="http", url="http://x/") for _ in range(3)
        ]
        pull_module.unique_labels(targets)
        labels = [t.label for t in targets]
        assert len(set(labels)) == 3
        assert all(len(label) <= mcp_skills.MAX_LABEL_LENGTH for label in labels)
        assert labels[1].endswith("-2") and labels[2].endswith("-3")

    @pytest.mark.parametrize(
        "name", ["CON", "nul.local", "Com1", "lpt9.example.com", "aux " * 30, "docs"]
    )
    def test_labels_are_safe_and_stable(self, name):
        label = mcp_skills.sanitize_label(name)
        assert mcp_skills.sanitize_label(label) == label
        assert mcp_skills.local_parts(f"skill://{label}/SKILL.md") == (label, "SKILL.md")
        assert len(label) <= mcp_skills.MAX_LABEL_LENGTH

    def test_device_names_change_before_the_first_dot(self):
        assert mcp_skills.sanitize_label("CON") == "server-con"
        assert mcp_skills.sanitize_label("nul.local") == "server-nul.local"

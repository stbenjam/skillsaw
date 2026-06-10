"""
Tests for the skillsaw language server (`skillsaw lsp`).

Unit tests exercise the violation→diagnostic conversion and the
workspace-lint plumbing directly.  The end-to-end test speaks real LSP
(Content-Length framed JSON-RPC) to a `python -m skillsaw lsp` subprocess
against a fixture workspace.
"""

import json
import queue
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest

pytest.importorskip("pygls")

from lsprotocol import types

from skillsaw.lsp.server import (
    SkillsawLanguageServer,
    build_linter,
    diagnostics_for_file,
    group_violations_by_file,
    violation_to_diagnostic,
)
from skillsaw.rule import RuleViolation, Severity
from skillsaw.rule_docs import rule_doc_url

FIXTURES = Path(__file__).parent / "fixtures"

UNLINKED_RULE = "content-unlinked-internal-reference"


def copy_workspace(tmp_path):
    dest = tmp_path / "workspace"
    shutil.copytree(FIXTURES / "lsp" / "workspace", dest)
    return dest


# ── Unit tests: diagnostic conversion ───────────────────────────


class TestViolationToDiagnostic:
    def _violation(self, severity=Severity.WARNING, line=8, file_path=Path("/tmp/CLAUDE.md")):
        return RuleViolation(
            rule_id="content-weak-language",
            severity=severity,
            message="Weak language",
            file_path=file_path,
            line=line,
        )

    def test_line_is_zero_based(self):
        diag = violation_to_diagnostic(self._violation(line=8))
        assert diag.range.start.line == 7
        assert diag.range.start.character == 0

    def test_severity_mapping(self):
        cases = {
            Severity.ERROR: types.DiagnosticSeverity.Error,
            Severity.WARNING: types.DiagnosticSeverity.Warning,
            Severity.INFO: types.DiagnosticSeverity.Information,
        }
        for severity, expected in cases.items():
            diag = violation_to_diagnostic(self._violation(severity=severity))
            assert diag.severity == expected

    def test_code_and_docs_url(self):
        diag = violation_to_diagnostic(self._violation())
        assert diag.code == "content-weak-language"
        assert diag.code_description.href == rule_doc_url("content-weak-language")
        assert diag.source == "skillsaw"

    def test_custom_rule_has_no_docs_url(self):
        v = self._violation()
        v.source = "custom"
        diag = violation_to_diagnostic(v)
        assert diag.code_description is None

    def test_no_line_anchors_to_top_of_file(self):
        diag = violation_to_diagnostic(self._violation(line=None))
        assert diag.range.start.line == 0
        assert diag.range.start.character == 0

    def test_range_spans_line_text(self):
        diag = violation_to_diagnostic(self._violation(line=8), line_text="some text here\n")
        assert diag.range.end.character == len("some text here")


class TestGroupViolations:
    def test_repo_level_violations_dropped(self):
        with_file = RuleViolation(
            rule_id="r1",
            severity=Severity.ERROR,
            message="m",
            file_path=Path("/tmp/a.md"),
        )
        repo_level = RuleViolation(rule_id="r2", severity=Severity.ERROR, message="m")
        grouped = group_violations_by_file([with_file, repo_level])
        assert list(grouped.keys()) == [Path("/tmp/a.md").resolve()]


# ── Unit tests: workspace lint plumbing ─────────────────────────


class TestServerLinting:
    def test_lint_workspace_groups_by_file(self, tmp_path):
        repo = copy_workspace(tmp_path)
        server = SkillsawLanguageServer()
        server.repo_root = repo
        by_file = server.lint_workspace()
        assert by_file is not None
        claude_md = (repo / "CLAUDE.md").resolve()
        assert claude_md in by_file
        assert any(v.rule_id == UNLINKED_RULE for v in by_file[claude_md])

    def test_diagnostics_for_file_spans_violation_line(self, tmp_path):
        repo = copy_workspace(tmp_path)
        linter = build_linter(repo)
        by_file = group_violations_by_file(linter.run())
        claude_md = (repo / "CLAUDE.md").resolve()
        diags = diagnostics_for_file(claude_md, by_file[claude_md])
        unlinked = [d for d in diags if d.code == UNLINKED_RULE]
        assert len(unlinked) == 1
        diag = unlinked[0]
        lines = claude_md.read_text(encoding="utf-8").splitlines()
        assert "scripts/build.sh" in lines[diag.range.start.line]
        assert diag.range.end.character == len(lines[diag.range.start.line])

    def test_safe_fixes_for_document(self, tmp_path):
        repo = copy_workspace(tmp_path)
        server = SkillsawLanguageServer()
        server.repo_root = repo
        claude_md = repo / "CLAUDE.md"
        source = claude_md.read_text(encoding="utf-8")
        fixes = server.safe_fixes_for_document(claude_md, source)
        assert len(fixes) == 1
        assert fixes[0].rule_id == UNLINKED_RULE
        assert "[scripts/build.sh](scripts/build.sh)" in fixes[0].fixed_content

    def test_safe_fixes_skipped_for_dirty_buffer(self, tmp_path):
        repo = copy_workspace(tmp_path)
        server = SkillsawLanguageServer()
        server.repo_root = repo
        fixes = server.safe_fixes_for_document(repo / "CLAUDE.md", "unsaved buffer content\n")
        assert fixes == []

    def test_invalidate_picks_up_disk_changes(self, tmp_path):
        repo = copy_workspace(tmp_path)
        server = SkillsawLanguageServer()
        server.repo_root = repo
        by_file = server.lint_workspace()
        claude_md = (repo / "CLAUDE.md").resolve()
        assert any(v.rule_id == UNLINKED_RULE for v in by_file.get(claude_md, []))

        content = claude_md.read_text(encoding="utf-8")
        claude_md.write_text(
            content.replace("scripts/build.sh", "[scripts/build.sh](scripts/build.sh)", 1),
            encoding="utf-8",
        )
        server.invalidate()
        by_file = server.lint_workspace()
        assert not any(v.rule_id == UNLINKED_RULE for v in by_file.get(claude_md, []))


# ── End-to-end: real LSP session over stdio ─────────────────────


class LspClient:
    """Minimal JSON-RPC client speaking LSP over a subprocess's stdio."""

    def __init__(self, cwd):
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "skillsaw", "lsp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(cwd),
        )
        self._next_id = 0
        self._messages = queue.Queue()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self):
        stream = self.proc.stdout
        while True:
            headers = {}
            line = stream.readline()
            if not line:
                return
            while line and line.strip():
                key, _, value = line.decode("ascii").partition(":")
                headers[key.strip().lower()] = value.strip()
                line = stream.readline()
            length = int(headers.get("content-length", 0))
            if not length:
                continue
            body = stream.read(length)
            self._messages.put(json.loads(body.decode("utf-8")))

    def send(self, method, params, request=False):
        message = {"jsonrpc": "2.0", "method": method, "params": params}
        if request:
            self._next_id += 1
            message["id"] = self._next_id
        body = json.dumps(message).encode("utf-8")
        frame = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body
        self.proc.stdin.write(frame)
        self.proc.stdin.flush()
        return message.get("id")

    def wait_for(self, predicate, timeout=30):
        """Return the first incoming message matching *predicate*."""
        while True:
            message = self._messages.get(timeout=timeout)
            if predicate(message):
                return message

    def initialize(self, root, capabilities=None):
        request_id = self.send(
            "initialize",
            {
                "processId": None,
                "rootUri": root.as_uri(),
                "capabilities": capabilities or {},
            },
            request=True,
        )
        self.wait_for(lambda m: m.get("id") == request_id)
        self.send("initialized", {})

    def respond(self, request_id, result=None):
        """Answer a server→client request."""
        body = json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}).encode("utf-8")
        frame = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body
        self.proc.stdin.write(frame)
        self.proc.stdin.flush()

    def shutdown(self):
        try:
            request_id = self.send("shutdown", None, request=True)
            self.wait_for(lambda m: m.get("id") == request_id, timeout=5)
            self.send("exit", None)
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()


@pytest.fixture
def lsp_session(tmp_path):
    repo = copy_workspace(tmp_path)
    client = LspClient(cwd=repo)
    yield client, repo
    client.shutdown()


def _is_publish_for(uri):
    return lambda m: (
        m.get("method") == "textDocument/publishDiagnostics" and m["params"]["uri"] == uri
    )


@pytest.mark.integration
class TestLspEndToEnd:
    def test_diagnostics_published_on_initialize(self, lsp_session):
        client, repo = lsp_session
        claude_uri = (repo / "CLAUDE.md").as_uri()
        client.initialize(repo)

        message = client.wait_for(_is_publish_for(claude_uri))
        diagnostics = message["params"]["diagnostics"]
        codes = {d["code"] for d in diagnostics}
        assert UNLINKED_RULE in codes
        diag = next(d for d in diagnostics if d["code"] == UNLINKED_RULE)
        assert diag["source"] == "skillsaw"
        assert diag["severity"] == 3  # Information
        assert diag["range"]["start"]["line"] == 7  # fixture line 8, zero-based
        assert diag["codeDescription"]["href"] == rule_doc_url(UNLINKED_RULE)

    def test_did_save_clears_fixed_diagnostics(self, lsp_session):
        client, repo = lsp_session
        claude_md = repo / "CLAUDE.md"
        claude_uri = claude_md.as_uri()
        client.initialize(repo)
        client.wait_for(_is_publish_for(claude_uri))

        content = claude_md.read_text(encoding="utf-8")
        claude_md.write_text(
            content.replace("scripts/build.sh", "[scripts/build.sh](scripts/build.sh)", 1),
            encoding="utf-8",
        )
        client.send(
            "textDocument/didSave",
            {"textDocument": {"uri": claude_uri}},
        )

        message = client.wait_for(_is_publish_for(claude_uri))
        codes = {d["code"] for d in message["params"]["diagnostics"]}
        assert UNLINKED_RULE not in codes

    def test_code_action_offers_safe_fix(self, lsp_session):
        client, repo = lsp_session
        claude_md = repo / "CLAUDE.md"
        claude_uri = claude_md.as_uri()
        client.initialize(repo)
        publish = client.wait_for(_is_publish_for(claude_uri))
        diag = next(d for d in publish["params"]["diagnostics"] if d["code"] == UNLINKED_RULE)

        client.send(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": claude_uri,
                    "languageId": "markdown",
                    "version": 1,
                    "text": claude_md.read_text(encoding="utf-8"),
                }
            },
        )
        request_id = client.send(
            "textDocument/codeAction",
            {
                "textDocument": {"uri": claude_uri},
                "range": diag["range"],
                "context": {"diagnostics": [diag]},
            },
            request=True,
        )
        response = client.wait_for(lambda m: m.get("id") == request_id)
        actions = response["result"]
        assert actions, "expected at least one quick fix"
        action = actions[0]
        assert action["kind"] == "quickfix"
        assert action["title"].startswith("skillsaw:")
        edits = action["edit"]["changes"][claude_uri]
        assert "[scripts/build.sh](scripts/build.sh)" in edits[0]["newText"]

    def test_dynamic_file_watcher_registration(self, lsp_session):
        client, repo = lsp_session
        claude_uri = (repo / "CLAUDE.md").as_uri()
        client.initialize(
            repo,
            capabilities={"workspace": {"didChangeWatchedFiles": {"dynamicRegistration": True}}},
        )

        register = client.wait_for(lambda m: m.get("method") == "client/registerCapability")
        client.respond(register["id"])
        methods = {r["method"] for r in register["params"]["registrations"]}
        assert "workspace/didChangeWatchedFiles" in methods

        # Diagnostics still flow after registration
        message = client.wait_for(_is_publish_for(claude_uri))
        assert any(d["code"] == UNLINKED_RULE for d in message["params"]["diagnostics"])

        # A watched-file change triggers a relint that sees the new content
        claude_md = repo / "CLAUDE.md"
        content = claude_md.read_text(encoding="utf-8")
        claude_md.write_text(
            content.replace("scripts/build.sh", "[scripts/build.sh](scripts/build.sh)", 1),
            encoding="utf-8",
        )
        client.send(
            "workspace/didChangeWatchedFiles",
            {"changes": [{"uri": claude_uri, "type": 2}]},
        )
        message = client.wait_for(_is_publish_for(claude_uri))
        codes = {d["code"] for d in message["params"]["diagnostics"]}
        assert UNLINKED_RULE not in codes

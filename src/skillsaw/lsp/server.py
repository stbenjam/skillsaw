"""
skillsaw language server built on pygls.

Publishes lint violations as LSP diagnostics for files in the workspace,
and offers safe deterministic autofixes as quick-fix code actions.

Linting is save-based: diagnostics reflect file contents on disk, not
unsaved editor buffers.  Because skillsaw has cross-file rules (e.g.
marketplace registration), every relint re-publishes diagnostics for the
whole workspace rather than just the changed file.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional, Set

from lsprotocol import types
from pygls import uris
from pygls.lsp.server import LanguageServer

from .. import __version__
from ..baseline import find_baseline, load_baseline
from ..config import LinterConfig, find_config
from ..context import RepositoryContext
from ..linter import Linter
from ..rule import AutofixConfidence, AutofixResult, RuleViolation, Severity
from ..rule_docs import rule_doc_url

logger = logging.getLogger(__name__)

SEVERITY_MAP = {
    Severity.ERROR: types.DiagnosticSeverity.Error,
    Severity.WARNING: types.DiagnosticSeverity.Warning,
    Severity.INFO: types.DiagnosticSeverity.Information,
}

# File patterns whose changes invalidate the cached repository context.
WATCHED_PATTERNS = (
    "**/*.md",
    "**/*.json",
    "**/*.yaml",
    "**/*.yml",
    "**/.skillsaw.yaml",
    "**/.claudelint.yaml",
    "**/.skillsaw-baseline.json",
)


def build_linter(root: Path) -> Linter:
    """Construct a Linter for *root* mirroring `skillsaw lint` discovery.

    Config and baseline are auto-discovered; a malformed config falls back
    to defaults rather than killing the server.
    """
    context = RepositoryContext(root)

    config = None
    config_path = find_config(root)
    if config_path:
        try:
            config = LinterConfig.from_file(config_path)
        except ValueError as e:
            logger.warning("Failed to load config %s: %s — using defaults", config_path, e)
    if config is None:
        config = LinterConfig.default()

    baseline = None
    baseline_path = find_baseline(config.config_dir or root)
    if baseline_path:
        try:
            baseline = load_baseline(baseline_path)
        except (ValueError, OSError) as e:
            logger.warning("Failed to load baseline %s: %s", baseline_path, e)

    return Linter(context, config, baseline=baseline)


def violation_to_diagnostic(
    violation: RuleViolation, line_text: Optional[str] = None
) -> types.Diagnostic:
    """Convert a RuleViolation to an LSP Diagnostic.

    Lines are anchored 0-based; violations without a line number attach to
    the top of the file.  When *line_text* is provided the diagnostic range
    spans the whole line so editors underline the offending text.
    """
    file_line = violation.file_line
    line = max(0, (file_line or 1) - 1)
    end_char = len(line_text.rstrip("\r\n")) if line_text is not None else 0

    code_description = None
    if violation.source == "builtin":
        code_description = types.CodeDescription(href=rule_doc_url(violation.rule_id))

    return types.Diagnostic(
        range=types.Range(
            start=types.Position(line=line, character=0),
            end=types.Position(line=line, character=end_char),
        ),
        message=violation.message,
        severity=SEVERITY_MAP.get(violation.severity, types.DiagnosticSeverity.Warning),
        code=violation.rule_id,
        code_description=code_description,
        source="skillsaw",
    )


def group_violations_by_file(
    violations: List[RuleViolation],
) -> Dict[Path, List[RuleViolation]]:
    """Group violations by resolved file path, dropping repo-level ones.

    Violations without a file path (whole-repository findings) cannot be
    anchored to a document and are not published as diagnostics.
    """
    by_file: Dict[Path, List[RuleViolation]] = {}
    for v in violations:
        if v.file_path is None:
            continue
        by_file.setdefault(v.file_path.resolve(), []).append(v)
    return by_file


def diagnostics_for_file(path: Path, violations: List[RuleViolation]) -> List[types.Diagnostic]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        lines = []

    diagnostics = []
    for v in violations:
        file_line = v.file_line
        line_text = None
        if file_line is not None and 1 <= file_line <= len(lines):
            line_text = lines[file_line - 1]
        elif file_line is None and lines:
            line_text = lines[0]
        diagnostics.append(violation_to_diagnostic(v, line_text))
    return diagnostics


class SkillsawLanguageServer(LanguageServer):
    """Language server that lints the workspace with skillsaw."""

    def __init__(self):
        super().__init__("skillsaw", __version__)
        self.repo_root: Optional[Path] = None
        self._linter: Optional[Linter] = None
        self._published_uris: Set[str] = set()

    def ensure_linter(self) -> Optional[Linter]:
        if self._linter is None and self.repo_root is not None:
            try:
                self._linter = build_linter(self.repo_root)
            except Exception as e:
                logger.error("Failed to initialize linter for %s: %s", self.repo_root, e)
        return self._linter

    def invalidate(self) -> None:
        """Drop cached linter state so the next lint sees current disk content."""
        from ..rules.builtin.utils import invalidate_read_caches

        invalidate_read_caches()
        self._linter = None

    def lint_workspace(self) -> Optional[Dict[Path, List[RuleViolation]]]:
        linter = self.ensure_linter()
        if linter is None:
            return None
        try:
            violations = linter.run()
        except Exception as e:
            logger.error("Lint failed: %s", e)
            return None
        return group_violations_by_file(violations)

    def publish_workspace_diagnostics(self) -> None:
        """Relint the workspace and publish diagnostics for every file.

        Files that previously had diagnostics but are now clean get an
        explicit empty publish so editors clear stale squiggles.
        """
        by_file = self.lint_workspace()
        if by_file is None:
            return

        published: Set[str] = set()
        for path, file_violations in sorted(by_file.items()):
            uri = uris.from_fs_path(str(path))
            if uri is None:
                continue
            self.text_document_publish_diagnostics(
                types.PublishDiagnosticsParams(
                    uri=uri,
                    diagnostics=diagnostics_for_file(path, file_violations),
                )
            )
            published.add(uri)

        for uri in self._published_uris - published:
            self.text_document_publish_diagnostics(
                types.PublishDiagnosticsParams(uri=uri, diagnostics=[])
            )
        self._published_uris = published

    def safe_fixes_for_document(self, doc_path: Path, doc_source: str) -> List[AutofixResult]:
        """Compute safe deterministic autofixes applicable to one document.

        Only fixes whose snapshot matches the current buffer are returned —
        a dirty buffer would otherwise be clobbered by the full-content edit.
        Renames are excluded; they cannot be expressed as a text edit.
        """
        linter = self.ensure_linter()
        if linter is None:
            return []
        try:
            _violations, fixes = linter.fix()
        except Exception as e:
            logger.error("Autofix computation failed: %s", e)
            return []

        resolved = doc_path.resolve()
        return [
            fix
            for fix in fixes
            if fix.confidence == AutofixConfidence.SAFE
            and fix.rename_from is None
            and fix.file_path.resolve() == resolved
            and fix.original_content == doc_source
            and fix.fixed_content != fix.original_content
        ]


def create_server() -> SkillsawLanguageServer:
    server = SkillsawLanguageServer()

    @server.feature(types.INITIALIZED)
    def initialized(ls: SkillsawLanguageServer, params: types.InitializedParams):
        root_path = ls.workspace.root_path
        if root_path:
            ls.repo_root = Path(root_path)
            logger.info("skillsaw lsp: workspace root %s", ls.repo_root)
        else:
            logger.info("skillsaw lsp: no workspace root — waiting for first didOpen")
        _register_file_watcher(ls)
        ls.publish_workspace_diagnostics()

    @server.feature(types.TEXT_DOCUMENT_DID_OPEN)
    def did_open(ls: SkillsawLanguageServer, params: types.DidOpenTextDocumentParams):
        # Diagnostics are workspace-wide and already published; the only
        # work on open is bootstrapping a root for single-file sessions.
        if ls.repo_root is None:
            fs_path = uris.to_fs_path(params.text_document.uri)
            if fs_path:
                ls.repo_root = Path(fs_path).parent
                ls.publish_workspace_diagnostics()

    @server.feature(types.TEXT_DOCUMENT_DID_SAVE)
    def did_save(ls: SkillsawLanguageServer, params: types.DidSaveTextDocumentParams):
        ls.invalidate()
        ls.publish_workspace_diagnostics()

    @server.feature(types.WORKSPACE_DID_CHANGE_WATCHED_FILES)
    def did_change_watched_files(
        ls: SkillsawLanguageServer, params: types.DidChangeWatchedFilesParams
    ):
        ls.invalidate()
        ls.publish_workspace_diagnostics()

    @server.feature(
        types.TEXT_DOCUMENT_CODE_ACTION,
        types.CodeActionOptions(code_action_kinds=[types.CodeActionKind.QuickFix]),
    )
    def code_action(
        ls: SkillsawLanguageServer, params: types.CodeActionParams
    ) -> List[types.CodeAction]:
        uri = params.text_document.uri
        fs_path = uris.to_fs_path(uri)
        if fs_path is None:
            return []
        try:
            doc = ls.workspace.get_text_document(uri)
        except Exception:
            return []

        actions = []
        for fix in ls.safe_fixes_for_document(Path(fs_path), doc.source):
            full_range = types.Range(
                start=types.Position(line=0, character=0),
                end=types.Position(line=len(doc.lines), character=0),
            )
            matching = [d for d in params.context.diagnostics if d.code == fix.rule_id]
            actions.append(
                types.CodeAction(
                    title=f"skillsaw: {fix.description}",
                    kind=types.CodeActionKind.QuickFix,
                    diagnostics=matching,
                    edit=types.WorkspaceEdit(
                        changes={
                            uri: [types.TextEdit(range=full_range, new_text=fix.fixed_content)]
                        }
                    ),
                )
            )
        return actions

    return server


def _register_file_watcher(ls: SkillsawLanguageServer) -> None:
    """Dynamically register file watchers so external changes (git pulls,
    other tools) invalidate the cached repository context.  Editors that
    don't support dynamic registration still get save-based relinting."""
    try:
        capabilities = ls.client_capabilities
        watched = capabilities and getattr(
            getattr(capabilities.workspace, "did_change_watched_files", None),
            "dynamic_registration",
            False,
        )
        if not watched:
            return
        ls.client_register_capability(
            types.RegistrationParams(
                registrations=[
                    types.Registration(
                        id="skillsaw-file-watcher",
                        method=types.WORKSPACE_DID_CHANGE_WATCHED_FILES,
                        register_options=types.DidChangeWatchedFilesRegistrationOptions(
                            watchers=[
                                types.FileSystemWatcher(glob_pattern=pattern)
                                for pattern in WATCHED_PATTERNS
                            ]
                        ),
                    )
                ]
            )
        )
    except Exception as e:
        logger.debug("File watcher registration failed: %s", e)


def start_server() -> None:
    """Run the language server over stdio (entry point for `skillsaw lsp`)."""
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    create_server().start_io()

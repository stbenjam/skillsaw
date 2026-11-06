const vscode = require('vscode');
const { runCli } = require('./runner');
const { parseReport, within } = require('./report');
const { matchDocuments } = require('./documents');
const { Scheduler } = require('./scheduler');

function activate(context) {
  const output = vscode.window.createOutputChannel('skillsaw');
  const folders = new Map();
  const config = (folder) => vscode.workspace.getConfiguration('skillsaw', folder.uri);
  const bounded = (value, fallback, min, max) =>
    Number.isInteger(value) ? Math.min(max, Math.max(min, value)) : fallback;
  const severity = {
    error: vscode.DiagnosticSeverity.Error,
    warning: vscode.DiagnosticSeverity.Warning,
    info: vscode.DiagnosticSeverity.Information,
  };
  const scheduler = new Scheduler(
    async (options) => {
      if (!vscode.workspace.isTrusted)
        throw new Error('Trust the workspace before running skillsaw.');
      const result = await runCli(options);
      if (result.stderr) output.appendLine(`[${options.cwd}] ${result.stderr}`);
      let report;
      try {
        report = parseReport(result.stdout);
      } catch (error) {
        output.appendLine(
          `[${options.cwd}] stdout (first 4000 characters): ${result.stdout.slice(0, 4000)}`,
        );
        throw error;
      }
      return { ...result, report };
    },
    (key, { code, report }) => {
      const state = folders.get(key);
      if (!state) return;
      state.report = report;
      void remap(state);
      state.error = null;
      output.appendLine(
        `[${state.folder.name}] exit ${code}; ${report.violations.length} findings (skillsaw ${report.version}).`,
      );
    },
    failed,
  );

  function failed(key, error) {
    const state = folders.get(key);
    if (!state) return;
    invalidate(state);
    output.appendLine(`[${state.folder.name}] ${error.message}`);
    if (state.error !== error.message) {
      state.error = error.message;
      void vscode.window
        .showErrorMessage(`skillsaw (${state.folder.name}): ${error.message}`, 'Show Output')
        .then((choice) => {
          if (choice === 'Show Output') output.show();
        });
    }
  }
  async function remap(state) {
    if (!state.report) return;
    state.mapping?.abort();
    const controller = new AbortController();
    state.mapping = controller;
    try {
      const targets = await matchDocuments(
        state.folder.uri.fsPath,
        state.report.violations,
        vscode.workspace.textDocuments,
        controller.signal,
        state.scope,
      );
      // Opening another alias replaces this mapping; any disk/config change,
      // folder removal or disposal cancels it and drops the cached report.
      if (controller.signal.aborted) return;
      const grouped = new Map();
      for (const target of targets) {
        if (target.documents.some((doc) => doc.isDirty)) continue;
        const diagnostic = new vscode.Diagnostic(
          new vscode.Range(target.line, 0, target.line, 0),
          target.message,
          severity[target.finding.severity],
        );
        diagnostic.code = target.finding.rule_id;
        diagnostic.source = 'skillsaw';
        const uris = target.documents.length
          ? target.documents.map((doc) => doc.uri)
          : [vscode.Uri.file(target.file)];
        for (const uri of uris) {
          const item = grouped.get(uri.toString()) ?? [uri, []];
          item[1].push(diagnostic);
          grouped.set(uri.toString(), item);
        }
      }
      state.diagnostics.clear();
      state.diagnostics.set([...grouped.values()]);
    } catch (error) {
      if (!controller.signal.aborted) failed(state.folder.uri.toString(), error);
    } finally {
      if (state.mapping === controller) state.mapping = null;
    }
  }
  function invalidate(state) {
    scheduler.invalidate(state.folder.uri.toString());
    state.mapping?.abort();
    state.report = null;
    state.diagnostics.clear();
  }
  function request(state, explicit = false) {
    invalidate(state);
    if (!vscode.workspace.isTrusted) return;
    const settings = config(state.folder);
    if (!explicit && !settings.get('runOnSave', true)) return;
    scheduler.request(
      state.folder.uri.toString(),
      {
        executable: settings.get('executable', 'skillsaw'),
        cwd: state.folder.uri.fsPath,
        timeoutMs: bounded(settings.get('timeoutMs'), 30000, 1000, 300000),
      },
      explicit ? 0 : bounded(settings.get('debounceMs'), 600, 100, 10000),
    );
  }
  function affected(uris, callback) {
    for (const state of folders.values()) {
      if (uris.some((uri) => uri.scheme === 'file' && within(state.scope, uri.fsPath)))
        callback(state);
    }
  }
  function syncFolders() {
    // VS Code transforms remote host files to file: URIs before this workspace
    // extension receives them, and transforms diagnostic URIs back for the UI.
    const current = new Map(
      (vscode.workspace.workspaceFolders ?? [])
        .filter((folder) => folder.uri.scheme === 'file')
        .map((folder) => [folder.uri.toString(), folder]),
    );
    for (const [key, state] of folders) {
      if (!current.has(key)) {
        invalidate(state);
        state.diagnostics.dispose();
        folders.delete(key);
      }
    }
    for (const [key, folder] of current) {
      if (!folders.has(key)) {
        const state = {
          folder,
          diagnostics: vscode.languages.createDiagnosticCollection('skillsaw'),
          report: null,
          mapping: null,
          scope: null,
          error: null,
        };
        folders.set(key, state);
      }
    }
    // A parent-root alias can refer to a nested root's finding. Share the
    // outermost open root for document matching and synchronous invalidation;
    // CLI requests still use each folder's own working directory and settings.
    for (const state of folders.values()) {
      let scope = state.folder.uri.fsPath;
      for (const candidate of folders.values())
        if (within(candidate.folder.uri.fsPath, scope)) scope = candidate.folder.uri.fsPath;
      if (state.scope !== scope) {
        state.scope = scope;
        request(state);
      }
    }
  }
  context.subscriptions.push(
    output,
    scheduler,
    {
      dispose() {
        for (const state of folders.values()) {
          invalidate(state);
          state.diagnostics.dispose();
        }
        folders.clear();
      },
    },
    vscode.commands.registerCommand('skillsaw.showOutput', () => output.show()),
    vscode.commands.registerCommand('skillsaw.lint', () => {
      if (!vscode.workspace.isTrusted) {
        void vscode.window.showWarningMessage('Trust the workspace before running skillsaw.');
        return;
      }
      if (!folders.size) {
        void vscode.window.showWarningMessage(
          'Open a folder on the extension host filesystem to lint with skillsaw.',
        );
        return;
      }
      for (const state of folders.values()) request(state, true);
    }),
    vscode.workspace.onDidOpenTextDocument((doc) =>
      affected([doc.uri], (state) => {
        if (config(state.folder).get('runOnSave', true)) request(state);
        else void remap(state);
      }),
    ),
    vscode.workspace.onDidSaveTextDocument((doc) => affected([doc.uri], request)),
    vscode.workspace.onDidChangeTextDocument((event) => {
      // A clean alias can reload after a save has already scheduled lint.
      // Replace that cancelled run; dirty buffers still only invalidate.
      if (event.contentChanges.length)
        affected([event.document.uri], event.document.isDirty ? invalidate : request);
    }),
    vscode.workspace.onDidCloseTextDocument((doc) =>
      affected([doc.uri], (state) => {
        if (config(state.folder).get('runOnSave', true)) request(state);
        else void remap(state);
      }),
    ),
    vscode.workspace.onDidCreateFiles((event) => affected(event.files, request)),
    vscode.workspace.onDidDeleteFiles((event) => affected(event.files, request)),
    vscode.workspace.onDidRenameFiles((event) =>
      affected(
        event.files.flatMap((file) => [file.oldUri, file.newUri]),
        request,
      ),
    ),
    vscode.workspace.onDidChangeWorkspaceFolders(syncFolders),
    vscode.workspace.onDidGrantWorkspaceTrust(() => {
      for (const state of folders.values()) request(state);
    }),
    vscode.workspace.onDidChangeConfiguration((event) => {
      for (const state of folders.values())
        if (event.affectsConfiguration('skillsaw', state.folder.uri)) request(state);
    }),
  );
  syncFolders();
}

module.exports = { activate };

const { realpath } = require('node:fs/promises');
const { location, within } = require('./report');

// Match only files already reported by the CLI to open editor documents.
// This does not discover artifacts or change the CLI's containment decisions.
async function matchDocuments(root, findings, documents, signal, scope) {
  const identities = new Map();
  function identity(file) {
    if (!identities.has(file))
      identities.set(
        file,
        realpath(file).catch(() => file),
      );
    return identities.get(file);
  }
  const open = new Map();
  for (const doc of documents) {
    signal.throwIfAborted();
    if (doc.uri.scheme !== 'file' || !within(scope, doc.uri.fsPath)) continue;
    const key = await identity(doc.uri.fsPath);
    const aliases = open.get(key) ?? [];
    aliases.push(doc);
    open.set(key, aliases);
  }
  const targets = [];
  for (const finding of findings) {
    signal.throwIfAborted();
    const target = location(root, finding);
    const aliases = open.size ? (open.get(await identity(target.file)) ?? []) : [];
    targets.push({ ...target, finding, documents: aliases });
  }
  return targets;
}

module.exports = { matchDocuments };

const path = require('node:path');

function within(root, file) {
  const relative = path.relative(root, file);
  return relative !== '..' && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative);
}

function parseReport(stdout) {
  const invalid = () =>
    new Error('Invalid skillsaw JSON report. Check the installed CLI and see skillsaw Output.');
  let report;
  try {
    report = JSON.parse(stdout);
  } catch {
    throw invalid();
  }
  const object = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
  const nonempty = (value) => typeof value === 'string' && value.length > 0;
  if (
    !object(report) ||
    !nonempty(report.version) ||
    !object(report.stats) ||
    !object(report.summary) ||
    !Array.isArray(report.violations) ||
    !['errors', 'warnings', 'info'].every(
      (key) => Number.isSafeInteger(report.summary[key]) && report.summary[key] >= 0,
    )
  ) {
    throw invalid();
  }
  for (const finding of report.violations) {
    if (
      !object(finding) ||
      !nonempty(finding.rule_id) ||
      !nonempty(finding.message) ||
      !['error', 'warning', 'info'].includes(finding.severity) ||
      !(
        finding.file_path === null ||
        (nonempty(finding.file_path) && !finding.file_path.includes('\0'))
      ) ||
      !(
        finding.line === null ||
        (Number.isSafeInteger(finding.line) && finding.line > 0 && finding.line <= 2147483647)
      )
    ) {
      throw invalid();
    }
  }
  return report;
}

function location(root, finding) {
  const name = finding.file_path;
  // The CLI deliberately redacts outside-root paths. Never invent a file for
  // that marker, or let malformed output navigate out of the requested root.
  const unavailable =
    name === null ||
    /^outside-repo[/\\][0-9a-f]{12}-/.test(name) ||
    path.isAbsolute(name) ||
    path.win32.isAbsolute(name) ||
    !within(root, path.resolve(root, name));
  return {
    file: unavailable ? root : path.resolve(root, name),
    line: unavailable ? 0 : (finding.line ?? 1) - 1,
    message: unavailable
      ? `${finding.message} [${name ?? 'workspace finding'}; location unavailable]`
      : finding.message,
  };
}

module.exports = { parseReport, location, within };

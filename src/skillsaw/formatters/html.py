"""HTML output formatter — self-contained report with inline CSS."""

import html
from typing import List

from ..rule import Rule, RuleViolation, Severity
from . import get_counts, relative_path


def format_html(
    violations: List[RuleViolation],
    context,
    rules: List[Rule],
    version: str,
    verbose: bool = False,
) -> str:
    errors, warnings, info = get_counts(violations)

    visible = [v for v in violations if verbose or v.severity != Severity.INFO]

    def severity_badge(sev: Severity) -> str:
        colors = {
            Severity.ERROR: ("#dc3545", "#fff"),
            Severity.WARNING: ("#e8a317", "#fff"),
            Severity.INFO: ("#0d6efd", "#fff"),
        }
        bg, fg = colors[sev]
        label = html.escape(sev.value)
        return (
            f'<span style="display:inline-block;padding:2px 10px;'
            f"border-radius:12px;font-size:0.85em;font-weight:600;"
            f'background:{bg};color:{fg}">{label}</span>'
        )

    def location(v: RuleViolation) -> str:
        rel = relative_path(v.file_path, context.root_path)
        if rel and v.line:
            return html.escape(f"{rel}:{v.line}")
        if rel:
            return html.escape(rel)
        return "-"

    severity_order = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}
    visible.sort(key=lambda v: (severity_order[v.severity], str(v.file_path or ""), v.line or 0))

    rows = ""
    for v in visible:
        rows += (
            "<tr>"
            f"<td>{severity_badge(v.severity)}</td>"
            f"<td><code>{html.escape(v.rule_id)}</code></td>"
            f"<td>{location(v)}</td>"
            f"<td>{html.escape(v.message)}</td>"
            "</tr>\n"
        )

    if visible:
        table_section = f"""\
    <table>
      <thead>
        <tr>
          <th>Severity</th>
          <th>Rule</th>
          <th>Location</th>
          <th>Message</th>
        </tr>
      </thead>
      <tbody>
        {rows}
      </tbody>
    </table>"""
    else:
        table_section = """\
    <section class="success-banner">
      All checks passed — no violations found.
    </section>"""

    info_count_row = ""
    if verbose:
        info_count_row = f'<span class="count-item count-info">Info: {info}</span>'

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>skillsaw Report</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      padding: 24px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                   Helvetica, Arial, sans-serif, "Apple Color Emoji",
                   "Segoe UI Emoji";
      background: #f8f9fa;
      color: #212529;
      line-height: 1.5;
    }}
    header {{
      margin-bottom: 24px;
    }}
    header h1 {{
      margin: 0 0 4px;
      font-size: 1.6em;
    }}
    header p {{
      margin: 0;
      color: #6c757d;
      font-size: 0.9em;
    }}
    .stats {{
      display: flex;
      flex-wrap: wrap;
      gap: 16px;
      margin-bottom: 24px;
    }}
    .stat-card {{
      flex: 1 1 140px;
      background: #fff;
      border-radius: 8px;
      padding: 16px 20px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    }}
    .stat-card .label {{
      font-size: 0.8em;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: #6c757d;
      margin-bottom: 4px;
    }}
    .stat-card .value {{
      font-size: 1.25em;
      font-weight: 600;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: #fff;
      border-radius: 8px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.08);
      overflow: hidden;
    }}
    thead th {{
      text-align: left;
      padding: 12px 16px;
      background: #e9ecef;
      font-size: 0.85em;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: #495057;
    }}
    tbody td {{
      padding: 10px 16px;
      border-top: 1px solid #e9ecef;
      vertical-align: top;
      font-size: 0.92em;
      white-space: pre-wrap;
    }}
    tbody tr:hover {{
      background: #f1f3f5;
    }}
    code {{
      background: #e9ecef;
      padding: 2px 6px;
      border-radius: 4px;
      font-size: 0.9em;
    }}
    .success-banner {{
      background: #d4edda;
      color: #155724;
      border-radius: 8px;
      padding: 20px 24px;
      font-weight: 600;
      text-align: center;
      box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    }}
    footer {{
      margin-top: 24px;
      padding-top: 16px;
      border-top: 1px solid #dee2e6;
      font-size: 0.9em;
      color: #6c757d;
      display: flex;
      flex-wrap: wrap;
      gap: 16px;
    }}
    .count-item {{
      font-weight: 600;
    }}
    .count-error {{ color: #dc3545; }}
    .count-warning {{ color: #e8a317; }}
    .count-info {{ color: #0d6efd; }}
  </style>
</head>
<body>
  <header>
    <h1>skillsaw Report</h1>
    <p>v{html.escape(version)}</p>
  </header>

  <section class="stats">
    <article class="stat-card">
      <div class="label">Repo Type</div>
      <div class="value">{html.escape(", ".join(sorted(t.value for t in context.repo_types if t.value != "unknown")) or "unknown")}</div>
    </article>
    <article class="stat-card">
      <div class="label">Plugins</div>
      <div class="value">{len(context.plugins)}</div>
    </article>
    <article class="stat-card">
      <div class="label">Skills</div>
      <div class="value">{len(context.skills)}</div>
    </article>
    <article class="stat-card">
      <div class="label">Rules Run</div>
      <div class="value">{len(rules)}</div>
    </article>
  </section>

  <main>
    {table_section}
  </main>

  <footer>
    <span class="count-item count-error">Errors: {errors}</span>
    <span class="count-item count-warning">Warnings: {warnings}</span>
    {info_count_row}
  </footer>
</body>
</html>
"""

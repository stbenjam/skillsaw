"""Codex's focused instruction view for ``skillsaw tree``."""

from __future__ import annotations

import json

from ..codex_instructions import CodexInstructionsNode
from ..context import RepositoryContext
from ..diagnostics import safe_display


def print_codex_instructions(context: RepositoryContext, fmt: str) -> int:
    nodes = context.lint_tree.find(CodexInstructionsNode)
    if not nodes:
        print("Error: Codex instruction selection is outside the retained authoring scope")
        return 1
    report = nodes[0].report(context.lint_tree)
    if fmt == "json":
        print(json.dumps(report, indent=2))
    else:
        lines = [
            "Codex project instructions (loader 0.162.1)",
            f"Root: {report['root']}",
            f"Requested cwd: {report['requested_cwd']}",
            f"Cwd: {report['cwd'] if report['cwd'] is not None else '(unresolved)'}",
            f"project_doc_max_bytes: {report['project_doc_max_bytes']:,} ({report['limit_source']})",
            "Precedence: " + " > ".join(report["candidate_filenames"]),
            f"Fallback source: {report['fallback_source']}",
            "Selected chain (root to cwd):",
        ]
        for entry in report["selected"]:
            sizes = ""
            if entry.get("cumulative_bytes") is not None:
                sizes = (
                    f" — {entry['file_bytes']:,} file bytes; {entry['charged_bytes']:,} charged; "
                    f"{entry['cumulative_bytes']:,} cumulative"
                )
            lines.append(f"  {entry['path']}: {entry['status']}{sizes}")
        if not report["selected"]:
            lines.append("  (none)")
        if report["complete"]:
            lines.append(
                f"Budget: {report['charged_bytes']:,}/{report['project_doc_max_bytes']:,} bytes; "
                f"rendered project text: {report['rendered_project_bytes']:,} bytes "
                f"({report['separator_bytes']} uncharged separator bytes)"
            )
        if report["affected_paths"]:
            lines.append("Truncated or omitted: " + ", ".join(report["affected_paths"]))
            lines.append("Reduce the selected chain or raise Codex's project_doc_max_bytes.")
        for name in report["ignored_fallback_filenames"]:
            lines.append(f"Ignored fallback with path syntax: {name!r}")
        for issue in report["issues"]:
            lines.append(f"Incomplete: {issue}")
        lines.append("Assumptions:")
        lines.extend("  " + assumption for assumption in report["assumptions"])
        print("\n".join(safe_display(line) for line in lines))
    # Inspection succeeds on a complete model, even when it diagnoses a cap.
    # Use the lint rule with --strict for a CI gate on that finding.
    return 0 if report["complete"] else 1

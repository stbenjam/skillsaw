"""
MCP server exposing skillsaw's core capabilities over the Model Context
Protocol (stdio transport).

Coding agents (Claude Code, Cursor, Codex CLI, Gemini CLI, ...) connect to
``skillsaw mcp`` to lint, grade, and fix the skills and instruction files
they are authoring without shelling out.

Every tool is deterministic and offline. All tools are read-only except
``fix`` with ``dry_run=false``, which writes skillsaw's deterministic
autofixes. Custom rules defined in the linted repository's
``.skillsaw.yaml`` are never executed (equivalent to ``--no-custom-rules``),
so the server never runs code from the repository under lint.

This module requires the optional ``mcp`` dependency
(``pip install 'skillsaw[mcp]'``); ``skillsaw.cli._mcp`` guards the import
and prints an install hint when it is missing.
"""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .config import LinterConfig, find_config
from .context import RepositoryContext
from .formatters import get_counts, relative_path
from .grade import compute_grade
from .linter import Linter
from .rule import AutofixConfidence
from .rule_docs import find_rule_class, load_rule_docs, rule_doc_url

_INSTRUCTIONS = (
    "Lint, grade, and autofix agent context files — Claude Code plugins and "
    "marketplaces, SKILL.md skills, commands, agents, hooks, and instruction "
    "files like CLAUDE.md / AGENTS.md — with skillsaw. Point the tools at the "
    "repository or directory you are authoring. Start with `lint`; use "
    "`explain_rule` to understand a violation, and `fix` (dry_run first) to "
    "apply deterministic autofixes."
)


# ---------------------------------------------------------------------------
# Shared internals
# ---------------------------------------------------------------------------


def _resolve_root(path: str) -> Path:
    """Normalize a tool's ``path`` argument to an existing directory."""
    root = Path(path).expanduser()
    if not root.exists():
        raise ValueError(f"Path not found: {path}")
    root = root.resolve()
    if root.is_file():
        root = root.parent
    return root


def _load_config(root: Path) -> LinterConfig:
    """Auto-discover and load .skillsaw.yaml (builtin defaults otherwise)."""
    config_path = find_config(root)
    if config_path is None:
        return LinterConfig.default()
    # Invalid config raises ValueError, which surfaces as a tool error.
    return LinterConfig.from_file(config_path)


def _build_linter(root: Path, config: LinterConfig, rule_ids=None, baseline=None):
    """RepositoryContext + Linter, mirroring the CLI's construction.

    ``no_custom_rules=True`` always: custom rules are arbitrary Python
    loaded from the linted repository, and the server must never execute
    repository content.
    """
    context = RepositoryContext(
        root,
        exclude_patterns=config.exclude_patterns,
        content_paths=config.content_paths,
    )
    linter = Linter(
        context,
        config,
        rule_ids=set(rule_ids) if rule_ids else None,
        baseline=baseline,
        no_custom_rules=True,
    )
    return context, linter


def _grade_for(context: RepositoryContext, violations) -> Any:
    tokens = sum(b.estimate_tokens() for b in context.lint_tree.content_blocks())
    return compute_grade(violations, tokens)


def _violation_dict(violation, root: Path) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "rule_id": violation.rule_id,
        "severity": violation.severity.value,
        "message": violation.message,
        "file": relative_path(violation.file_path, root),
        "line": violation.file_line,
        "source": violation.source,
    }
    if violation.source == "builtin":
        result["docs"] = rule_doc_url(violation.rule_id)
    return result


def explain_rule_markdown(rule_id: str) -> str:
    """Long-form markdown for one rule — same content ``skillsaw explain``
    prints, without the terminal colors or per-repository effective config.

    Raises ValueError (with close-match suggestions) for unknown rules.
    """
    rule_class, plugin_name, known_ids = find_rule_class(rule_id)
    if rule_class is None:
        close = difflib.get_close_matches(rule_id, known_ids, n=3)
        hint = f" Did you mean: {', '.join(close)}?" if close else ""
        raise ValueError(
            f"Unknown rule '{rule_id}'.{hint} Use the list_rules tool to see all rules."
        )

    defaults = LinterConfig.default()
    rule = rule_class(defaults.get_rule_config(rule_id))
    default_enabled = defaults.get_rule_config(rule_id).get("enabled", True)
    autofix_label = "auto" if rule.supports_autofix else "none"

    meta = f"severity: {rule.severity.value}, autofix: {autofix_label}, since {rule.since}"
    if plugin_name:
        meta += f", plugin: {plugin_name}"

    lines = [f"# {rule_id}", "", f"({meta})", "", rule.description]

    long_docs = load_rule_docs(rule_id)
    if long_docs:
        lines += ["", long_docs]

    if rule.repo_types:
        # repo_types may mix RepositoryType members with plugin type names.
        repo_types_str = ", ".join(sorted(getattr(t, "value", t) for t in rule.repo_types))
        lines += ["", f"**Applies to repo types:** {repo_types_str}"]

    lines += [
        "",
        "## Configuration (.skillsaw.yaml)",
        "",
        "```yaml",
        "rules:",
        f"  {rule_id}:",
        f"    enabled: {LinterConfig._yaml_value(default_enabled)}  # true | false | auto",
        f"    severity: {rule.severity.value}  # error | warning | info",
    ]
    for param_name, param_info in rule.config_schema.items():
        default_val = LinterConfig._yaml_value(param_info.get("default"), indent=6)
        desc = param_info.get("description", "")
        if default_val.startswith("\n"):
            lines.append(f"    {param_name}:  # {desc}{default_val}")
        else:
            lines.append(f"    {param_name}: {default_val}  # {desc}")
    lines.append("```")

    if plugin_name is None:
        # Plugin rules have no page on the skillsaw documentation site.
        lines += ["", f"Docs: {rule_doc_url(rule_id)}"]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Server factory
# ---------------------------------------------------------------------------


def create_server() -> FastMCP:
    """Build the skillsaw MCP server with all tools registered."""
    # FastMCP's default INFO logging echoes every rule decision to stderr;
    # WARNING keeps the transport chatter out of agent logs.
    server = FastMCP("skillsaw", instructions=_INSTRUCTIONS, log_level="WARNING")

    _read_only = ToolAnnotations(readOnlyHint=True, idempotentHint=True)

    @server.tool(annotations=_read_only)
    def lint(
        path: str,
        rules: Optional[List[str]] = None,
        strict: bool = False,
    ) -> Dict[str, Any]:
        """Lint a repository of agent context files (skills, plugins,
        CLAUDE.md/AGENTS.md, commands, agents, hooks, marketplaces).

        Args:
            path: Repository or directory to lint (a file path lints its
                containing directory).
            rules: Optional rule ids to run exclusively (default: all
                enabled rules).
            strict: Treat warnings as failures, like ``skillsaw lint
                --strict``.

        Returns violations (rule_id, severity, message, file, line, docs
        URL), summary counts, the repository's letter grade, and a
        ``passed`` verdict. Respects the repository's ``.skillsaw.yaml``
        and baseline file, exactly like ``skillsaw lint``.
        """
        root = _resolve_root(path)
        config = _load_config(root)

        baseline = None
        from .baseline import find_baseline, load_baseline

        baseline_path = find_baseline(config.config_dir or root)
        if baseline_path:
            try:
                baseline = load_baseline(baseline_path)
            except (ValueError, OSError):
                baseline = None

        context, linter = _build_linter(root, config, rule_ids=rules, baseline=baseline)
        violations = linter.run()
        grade = _grade_for(context, violations)

        errors, warnings, info = get_counts(violations)
        fail_level = "warning" if strict else config.effective_fail_level()
        failed = (
            errors > 0
            or (fail_level in ("warning", "info") and warnings > 0)
            or (fail_level == "info" and info > 0)
        )

        return {
            "path": str(root),
            "passed": not failed,
            "violations": [_violation_dict(v, root) for v in violations],
            "summary": {
                "errors": errors,
                "warnings": warnings,
                "info": info,
                "total": len(violations),
                "baseline_suppressed": linter.baseline_suppressed_count,
            },
            "grade": grade.to_dict(),
        }

    @server.tool(annotations=_read_only)
    def grade(path: str) -> Dict[str, Any]:
        """Grade a repository's agent-context quality (A+ through F).

        Same scale as the skillsaw badge: weighted violation density per
        10,000 estimated content tokens sets the letter, and errors knock
        off whole letters. Ignores any baseline so the grade reflects all
        violations.
        """
        root = _resolve_root(path)
        config = _load_config(root)
        context, linter = _build_linter(root, config)
        violations = linter.run()
        result = _grade_for(context, violations)
        return {
            "path": str(root),
            "letter": result.letter,
            "density": round(result.density, 2),
            "content_tokens": result.content_tokens,
            "errors": result.errors,
            "warnings": result.warnings,
            "info": result.info,
        }

    @server.tool(annotations=_read_only)
    def explain_rule(rule_id: str) -> str:
        """Explain a lint rule: what it checks, why it exists, bad/good
        examples, and its configuration options — the same long-form
        documentation ``skillsaw explain`` prints. Errors for unknown rule
        ids, with close-match suggestions.
        """
        return explain_rule_markdown(rule_id)

    @server.tool(annotations=_read_only)
    def list_rules() -> Dict[str, Any]:
        """List every available lint rule (builtin and installed plugins)
        with its one-line description, default severity, and whether it
        supports autofix.
        """
        from .plugins import load_plugins
        from .rules.builtin import BUILTIN_RULES

        entries = []
        for rule_class in BUILTIN_RULES:
            rule = rule_class()
            entries.append(
                {
                    "rule_id": rule.rule_id,
                    "description": rule.description,
                    "default_severity": rule.default_severity().value,
                    "autofix": rule.supports_autofix,
                    "docs": rule_doc_url(rule.rule_id),
                }
            )
        for plugin in load_plugins():
            if plugin.error:
                continue
            for rule_class in plugin.rule_classes:
                try:
                    rule = rule_class()
                except Exception:
                    continue
                entries.append(
                    {
                        "rule_id": rule.rule_id,
                        "description": rule.description,
                        "default_severity": rule.default_severity().value,
                        "autofix": rule.supports_autofix,
                        "plugin": plugin.name,
                    }
                )
        return {"rules": entries, "count": len(entries)}

    @server.tool(
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True)
    )
    def fix(path: str, dry_run: bool = True, suggest: bool = False) -> Dict[str, Any]:
        """Apply (or preview) skillsaw's deterministic autofixes.

        Args:
            path: Repository or directory to fix.
            dry_run: Preview only — report what would change without
                modifying any file (default: true).
            suggest: Also apply suggest-confidence fixes, not just safe
                ones (like ``skillsaw fix --suggest``).

        Returns the fixes applied (or previewed), fixes that need
        ``suggest=true``, and a per-file summary.
        """
        root = _resolve_root(path)
        config = _load_config(root)
        confidence = AutofixConfidence.SUGGEST if suggest else AutofixConfidence.SAFE

        context, linter = _build_linter(root, config)
        applied, suggested = linter.fix_and_apply(confidence, dry_run=dry_run)

        # A skill-directory rename changes discovery, unlocking fixes a
        # single pass can't see — same follow-up run `skillsaw fix` does.
        if not dry_run and any(f.rule_id == "agentskill-name" for f in applied):
            context, linter = _build_linter(root, config)
            more_applied, more_suggested = linter.fix_and_apply(confidence)
            applied.extend(more_applied)
            suggested.extend(more_suggested)

        def _fix_dict(fix_result):
            return {
                "file": relative_path(fix_result.file_path, root),
                "rule_id": fix_result.rule_id,
                "description": fix_result.description,
            }

        per_file: Dict[str, int] = {}
        for fix_result in applied:
            key = relative_path(fix_result.file_path, root)
            per_file[key] = per_file.get(key, 0) + 1

        return {
            "path": str(root),
            "dry_run": dry_run,
            "fixes": [_fix_dict(f) for f in applied],
            "suggested": [_fix_dict(f) for f in suggested],
            "summary": {
                "fixed": len(applied),
                "suggested": len(suggested),
                "files": per_file,
            },
        }

    return server

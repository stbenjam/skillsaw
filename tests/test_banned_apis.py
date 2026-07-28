"""Ratchet test banning new bare ``Path.resolve()`` calls in skillsaw source.

``Path.resolve()`` raises ``OSError``, ``ValueError``, or ``RuntimeError``
on hostile input (symlink loops, embedded NULs, unreadable parents), which
is why ``skillsaw.paths`` provides ``safe_resolve()`` and
``contained_resolve()``. This test freezes the set of files that already
contain bare ``.resolve()`` calls: existing debt is grandfathered per
issue #463, but any *new* file reaching for bare ``.resolve()`` fails here
and must use the ``skillsaw.paths`` wrappers instead. Paying down a
grandfathered file is welcome — remove it from the allowlist when you do.
"""

import ast
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent.parent / "src" / "skillsaw"

# Files (relative to src/skillsaw) that contained bare ``.resolve()`` calls
# when the ratchet was introduced. Do not add to this list — new code must
# use ``safe_resolve()`` / ``contained_resolve()`` from ``skillsaw.paths``.
# ``paths.py`` itself is exempt: it is where the wrappers live.
GRANDFATHERED_BARE_RESOLVE = frozenset(
    {
        "baseline.py",
        "blocks/coderabbit.py",
        "blocks/frontmatter.py",
        "blocks/promptfoo.py",
        "cli/_badge.py",
        "cli/_baseline.py",
        "cli/_explain.py",
        "cli/_helpers.py",
        "cli/_lint.py",
        "config.py",
        "context.py",
        "docs/extractor.py",
        "formats/promptfoo.py",
        "formatters/text.py",
        "lint_target.py",
        "lint_tree.py",
        "linter.py",
        "marketplace/add.py",
        "marketplace/init.py",
        "rules/builtin/agentskills/unreferenced_files.py",
        "rules/builtin/commands/naming.py",
        "rules/builtin/content/broken_internal_reference.py",
        "rules/builtin/content/instruction_drift.py",
        "rules/builtin/content/unlinked_internal_reference.py",
        "rules/builtin/instructions/imports_valid.py",
        "rules/builtin/marketplace/registration.py",
        "rules/builtin/plugins/json_required.py",
        "utils.py",
    }
)


def _files_with_bare_resolve() -> set:
    """Relative paths of source files containing a bare ``.resolve()`` call.

    The scan is AST-based so docstrings and comments mentioning
    ``path.resolve()`` do not count — only an actual attribute call named
    ``resolve`` does. ``safe_resolve()``/``contained_resolve()`` are plain
    function calls, not attribute calls, so they never match.
    """
    offenders = set()
    for py in sorted(SRC_ROOT.rglob("*.py")):
        rel = py.relative_to(SRC_ROOT).as_posix()
        if rel == "paths.py":
            continue
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "resolve"
            ):
                offenders.add(rel)
                break
    return offenders


class TestBannedApis:
    def test_no_new_bare_resolve_calls(self):
        offenders = _files_with_bare_resolve()
        new_offenders = offenders - GRANDFATHERED_BARE_RESOLVE
        assert not new_offenders, (
            "Bare Path.resolve() calls found in files outside the grandfathered "
            f"allowlist: {sorted(new_offenders)}. Use safe_resolve() or "
            "contained_resolve() from skillsaw.paths instead — Path.resolve() "
            "raises on symlink loops, embedded NULs, and unreadable parents."
        )

    def test_allowlist_has_no_stale_entries(self):
        """A paid-down file must also leave the allowlist, so the ratchet
        only ever tightens."""
        offenders = _files_with_bare_resolve()
        stale = GRANDFATHERED_BARE_RESOLVE - offenders
        assert not stale, (
            "Allowlist entries no longer contain bare .resolve() calls — "
            f"remove them from GRANDFATHERED_BARE_RESOLVE: {sorted(stale)}"
        )

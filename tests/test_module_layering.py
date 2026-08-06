"""
Module-layering regression tests.

The lint-tree block hierarchy lives in the core ``skillsaw.blocks`` module and
the promptfoo format helpers in ``skillsaw.formats.promptfoo`` — extracted out
of the leaf rule package ``skillsaw.rules.builtin.content_analysis`` so that
core modules no longer depend on a rule package.

These tests lock in two things:

* the extraction did not reintroduce an import cycle (importing a core module
  *first*, before anything pulls in ``rules.builtin``, must not fail), and
* every legacy import path still resolves to the same object, so existing
  rules / custom rules that import from the old locations keep working.
"""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src" / "skillsaw"


# ---------------------------------------------------------------------------
# Import-cycle regression
# ---------------------------------------------------------------------------

# Each of these modules transitively reaches the block hierarchy / format
# helpers.  Importing any of them as the very first skillsaw import (in a fresh
# interpreter, before ``rules.builtin``'s eager ``__init__`` has run) used to
# crash with "partially initialized module 'skillsaw.blocks'".
CYCLE_SENSITIVE_MODULES = [
    "skillsaw.blocks",
    "skillsaw.utils",
    "skillsaw.formats.promptfoo",
    "skillsaw.lint_tree",
    "skillsaw.docs.extractor",
    "skillsaw.rules.builtin.content_analysis",
    "skillsaw.rules.builtin.utils",
    "skillsaw.cli",
]


@pytest.mark.parametrize("module", CYCLE_SENSITIVE_MODULES)
def test_module_importable_as_first_import(module):
    """A fresh interpreter must import each module standalone without cycling."""
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"`import {module}` failed as a first import:\n{result.stderr}"


# ---------------------------------------------------------------------------
# Backward-compat re-exports
# ---------------------------------------------------------------------------


def test_content_analysis_reexports_are_the_canonical_blocks():
    """Block types imported from content_analysis are the same objects as blocks."""
    import skillsaw.blocks as blocks
    import skillsaw.rules.builtin.content_analysis as ca

    for name in (
        "ContentBlock",
        "FileContentBlock",
        "FrontmatteredBlock",
        "JsonConfigBlock",
        "SkillBlock",
        "CommandBlock",
        "AgentBlock",
        "McpBlock",
        "HooksBlock",
        "SettingsBlock",
        "CodeRabbitContentBlock",
        "PromptfooPromptBlock",
        "ContentFile",
        "ParsedFrontmatterBlock",
        "gather_all_content_blocks",
        "_extract_instructions",
    ):
        assert getattr(ca, name) is getattr(blocks, name), name


def test_promptfoo_helpers_reexport_public_format_module():
    """Legacy underscore helpers must be the public formats.promptfoo functions."""
    import skillsaw.formats.promptfoo as fmt
    from skillsaw.rules.builtin.promptfoo import _helpers

    assert _helpers._is_promptfoo_config is fmt.is_promptfoo_config
    assert _helpers._resolve_file_ref is fmt.resolve_file_ref
    assert _helpers._extract_file_refs is fmt.extract_file_refs
    assert _helpers._PROMPTFOO_KEYS is fmt.PROMPTFOO_KEYS


def test_utils_shim_reexports_core_utils():
    """The rules.builtin.utils shim must expose the core skillsaw.utils objects."""
    import skillsaw.utils as core
    import skillsaw.rules.builtin.utils as shim

    for name in (
        "read_text",
        "read_json",
        "read_yaml",
        "read_yaml_commented",
        "parse_frontmatter",
        "commented_item_line",
        "_FRONTMATTER_RE",
        "_extract_frontmatter_text",
    ):
        assert getattr(shim, name) is getattr(core, name), name


def test_context_reexports_canonical_plugin_provenance():
    """The pre-extraction context import path remains compatible."""
    from skillsaw.context import PluginProvenance as legacy
    from skillsaw.repository_provenance import PluginProvenance

    assert legacy is PluginProvenance


# ---------------------------------------------------------------------------
# Architectural invariant: core blocks/formats must not depend on the rules pkg
# ---------------------------------------------------------------------------


def _core_module_files():
    """Every top-level core module, blocks/*, and the promptfoo format helper."""
    files = sorted(str(p.relative_to(SRC)) for p in SRC.glob("*.py"))
    files.extend(sorted(str(p.relative_to(SRC)) for p in (SRC / "blocks").glob("*.py")))
    files.extend(sorted(str(p.relative_to(SRC)) for p in (SRC / "formats").glob("*.py")))
    return files


@pytest.mark.parametrize("rel_path", _core_module_files())
def test_core_module_does_not_import_rules_package(rel_path):
    """Core modules must not import rules.builtin at module load time.

    Function-local imports are deliberate lazy dependencies. A top-level edge
    is the inverted layer that creates an import cycle.
    """
    tree = ast.parse((SRC / rel_path).read_text())
    offenders = []
    # Module-level includes imports nested in top-level `try:`/`if` blocks —
    # those still execute at load time — but not function/class bodies.
    # Class bodies execute at import time, so only function scopes are
    # deliberate lazy-import territory.
    scopes = (ast.FunctionDef, ast.AsyncFunctionDef)
    stack = list(tree.body)
    while stack:
        node = stack.pop()
        if isinstance(node, scopes):
            continue
        # `from skillsaw.rules.builtin... import x`
        if isinstance(node, ast.ImportFrom) and node.module and "rules.builtin" in node.module:
            offenders.append(node.module)
        # `import skillsaw.rules.builtin...`
        elif isinstance(node, ast.Import):
            offenders.extend(a.name for a in node.names if "rules.builtin" in a.name)
        stack.extend(ast.iter_child_nodes(node))
    assert not offenders, f"{rel_path} imports from the rules package: {offenders}"


@pytest.mark.parametrize("path", sorted((SRC / "discovery").glob("*.py")))
def test_discovery_modules_are_state_free(path):
    """Discovery may take callbacks from context, but must never import it."""
    tree = ast.parse(path.read_text())
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            imports.append(module)
            imports.extend(f"{module}.{alias.name}" for alias in node.names)
    offenders = [name for name in imports if "context" in name.split(".")]
    assert not offenders, f"{path.relative_to(SRC)} imports context: {offenders}"


def test_context_stays_below_repository_model_budget():
    """Keep filesystem walks from accreting back into the orchestrator."""
    assert len((SRC / "context.py").read_text().splitlines()) < 900

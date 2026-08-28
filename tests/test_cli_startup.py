"""What the CLI is allowed to import before it has anything to say.

skillsaw's first line of output arrives only after every module on the
path to it has been imported, and the modules that do the linting —
repository discovery, the block hierarchy, the markdown parser, the rule
registry, both YAML parsers — are most of that cost. Deferring them until
after the banner is what separates a tool that answers immediately from
one that appears to hang, and a single module-scope import puts them all
back. These tests pin the boundary.

Each runs in a fresh interpreter: ``sys.modules`` in the test process
already holds everything, so an in-process check would pass vacuously.
"""

import subprocess
import sys

# Imported lazily on purpose; see the module docstring.
_DEFERRED = (
    "skillsaw.context",
    "skillsaw.linter",
    "skillsaw.config",
    "skillsaw.rules.builtin",
    "skillsaw.markdown_doc",
    "markdown_it",
    "yaml",
    "ruamel.yaml",
    "importlib.metadata",
)


def _modules_after(statement: str) -> set:
    program = f"import sys\n{statement}\nprint('\\n'.join(sorted(sys.modules)))"
    result = subprocess.run(
        [sys.executable, "-c", program], capture_output=True, text=True, check=True
    )
    return set(result.stdout.split())


def test_importing_the_cli_pulls_in_nothing_that_lints():
    loaded = _modules_after("import skillsaw.cli")

    assert not loaded.intersection(_DEFERRED), sorted(loaded.intersection(_DEFERRED))


def test_building_the_parser_pulls_in_nothing_that_lints():
    """``--type``'s choices and ``--fail-on``'s levels are the temptation here.

    Both used to be read off modules that can lint, which meant every
    invocation paid for them just to render a help string.
    """
    loaded = _modules_after("from skillsaw.cli._parser import _build_parser\n_build_parser()")

    assert not loaded.intersection(_DEFERRED), sorted(loaded.intersection(_DEFERRED))


def test_the_package_exports_still_resolve():
    """The lazy re-exports must behave exactly like the eager ones did."""
    import skillsaw

    assert skillsaw.Rule.__module__ == "skillsaw.rule"
    assert skillsaw.Linter.__module__ == "skillsaw.linter"
    assert skillsaw.RepositoryContext.__module__ == "skillsaw.context"
    assert skillsaw.Severity.ERROR.value == "error"
    assert set(dir(skillsaw)) == set(skillsaw.__all__)


def test_version_reports_the_running_package():
    from skillsaw import __version__
    from skillsaw.cli._config import _get_version

    assert _get_version() == __version__

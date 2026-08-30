"""Process-global warning display behavior for embedded CLI calls."""

from __future__ import annotations

import functools
import sys
import warnings

from skillsaw.cli._helpers import install_warning_display
from tests.cli_runner import run_cli


def _emit_ordinary_warning() -> None:
    warnings.showwarning(UserWarning("ordinary"), UserWarning, "example.py", 7)


def test_warning_display_install_is_idempotent_past_recursion_limit(monkeypatch):
    downstream = []

    def record(*args, **kwargs):
        downstream.append((args, kwargs))

    monkeypatch.setattr(warnings, "showwarning", record)
    install_warning_display()
    installed = warnings.showwarning

    for _ in range(sys.getrecursionlimit() + 100):
        install_warning_display()

    assert warnings.showwarning is installed
    _emit_ordinary_warning()
    assert len(downstream) == 1


def test_warning_display_rewraps_an_external_replacement(monkeypatch):
    downstream = []

    def record(*args, **kwargs):
        downstream.append((args, kwargs))

    monkeypatch.setattr(warnings, "showwarning", record)
    install_warning_display()
    first_skillsaw_handler = warnings.showwarning

    @functools.wraps(first_skillsaw_handler)
    def external_handler(*args, **kwargs):
        return first_skillsaw_handler(*args, **kwargs)

    warnings.showwarning = external_handler
    install_warning_display()
    replacement = warnings.showwarning
    install_warning_display()

    assert replacement is warnings.showwarning
    assert replacement is not external_handler
    _emit_ordinary_warning()
    assert len(downstream) == 1


def test_repeated_in_process_cli_calls_keep_one_warning_handler(monkeypatch):
    downstream = []

    def record(*args, **kwargs):
        downstream.append((args, kwargs))

    monkeypatch.setattr(warnings, "showwarning", record)

    first = run_cli(["--version"])
    installed = warnings.showwarning
    second = run_cli(["--version"])

    assert first.returncode == second.returncode == 0
    assert warnings.showwarning is installed
    _emit_ordinary_warning()
    assert len(downstream) == 1


def test_warning_display_cooperates_with_catch_warnings(monkeypatch):
    monkeypatch.setattr(warnings, "showwarning", warnings.showwarning)
    before = warnings.showwarning

    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        install_warning_display()
        warnings.warn("record me", UserWarning)

    assert [str(item.message) for item in recorded] == ["record me"]
    assert warnings.showwarning is before

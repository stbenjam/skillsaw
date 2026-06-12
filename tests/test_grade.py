"""
Tests for the repository quality grade (skillsaw.grade) and the
`skillsaw badge` subcommand.
"""

import json
import subprocess
import sys

import skillsaw.grade as grade_mod
from skillsaw.grade import Grade, compute_grade, LETTER_NOTCHES
from skillsaw.rule import RuleViolation, Severity

from .test_integration import FIXTURES, copy_fixture, run_lint, summary


def _violations(errors=0, warnings=0, info=0):
    out = []
    for i in range(errors):
        out.append(RuleViolation("test-error", Severity.ERROR, f"error {i}"))
    for i in range(warnings):
        out.append(RuleViolation("test-warning", Severity.WARNING, f"warning {i}"))
    for i in range(info):
        out.append(RuleViolation("test-info", Severity.INFO, f"info {i}"))
    return out


# ── compute_grade ────────────────────────────────────────────────


def test_zero_violations_is_a_plus():
    grade = compute_grade([], content_tokens=100)
    assert grade.letter == "A+"
    assert grade.density == 0.0
    assert grade.color == "brightgreen"


def test_density_normalizes_by_tokens():
    # 17 warnings in a huge marketplace is near-pristine...
    big = compute_grade(_violations(warnings=17), content_tokens=5_000_000)
    assert big.letter == "A+"
    # ...but 17 warnings in one small skill drops it six notches.
    small = compute_grade(_violations(warnings=17), content_tokens=2_000)
    assert small.letter == "C+"


def test_small_repos_floor_at_one_unit():
    # A tiny skill with a couple of warnings loses one notch, not the
    # whole scale (one warning at weight 0.75 stays under the A+ line).
    assert compute_grade(_violations(warnings=1), content_tokens=500).letter == "A+"
    grade = compute_grade(_violations(warnings=2), content_tokens=500)
    assert grade.letter == "A"
    assert grade.density == 1.5


def test_density_bands():
    # A+ is exclusive (< 1.0); after that every 2.0 density units cost a
    # notch. Calibrated so real-world community marketplaces (~10-14
    # density) land around B-/C+, not F. 10 info = 1.0 density unit.
    for info, letter in [
        (0, "A+"),
        (9, "A+"),
        (10, "A"),
        (29, "A"),
        (30, "A-"),
        (50, "B+"),
        (110, "C+"),
        (130, "C"),
        (210, "F"),
        (500, "F"),
    ]:
        grade = compute_grade(_violations(info=info), content_tokens=10_000)
        assert grade.letter == letter, f"{info} info/10k tokens -> {grade.letter}"


def test_info_calibration_anchor():
    # 1 info per 10k tokens must not dent the score.
    assert compute_grade(_violations(info=1), content_tokens=10_000).letter == "A+"
    # ~10 info per 10k tokens takes A+ to A.
    assert compute_grade(_violations(info=10), content_tokens=10_000).letter == "A"


def test_errors_knock_off_whole_letters():
    # Errors are not diluted by repository size.
    tokens = 5_000_000
    assert compute_grade(_violations(errors=1), content_tokens=tokens).letter == "B+"
    assert compute_grade(_violations(errors=5), content_tokens=tokens).letter == "C+"
    assert compute_grade(_violations(errors=25), content_tokens=tokens).letter == "D+"


def test_errors_stack_with_density():
    # Density 1.75 (error 1.0 + warning 0.75) lands A; the error's
    # letter knockdown (3 notches) takes it to B.
    grade = compute_grade(_violations(errors=1, warnings=1), content_tokens=10_000)
    assert grade.letter == "B"


def test_grade_floors_at_f():
    grade = compute_grade(_violations(errors=100, warnings=100), content_tokens=100)
    assert grade.letter == "F"
    assert grade.color == "red"


def test_letter_notches_are_well_formed():
    assert LETTER_NOTCHES[0] == "A+"
    assert LETTER_NOTCHES[-1] == "F"
    for letter in LETTER_NOTCHES:
        assert Grade(letter, 0, 0, 0, 0, 0).color  # every notch has a color


# ── Fixed scoring constants ──────────────────────────────────────


def test_weights_are_fixed_constants():
    # The grade is deliberately NOT configurable — a skillsaw badge must
    # mean the same thing on every repository. These values changing is
    # a breaking change to every published badge; bump knowingly.
    assert grade_mod.ERROR_WEIGHT == 1.0
    assert grade_mod.WARNING_WEIGHT == 0.75
    assert grade_mod.INFO_WEIGHT == 0.1
    assert grade_mod.DENSITY_PER_NOTCH == 2.0
    assert grade_mod.A_PLUS_THRESHOLD == 1.0
    assert not hasattr(grade_mod, "GradeSettings")


# Every property the shields.io endpoint schema accepts — it rejects
# payloads containing anything else, so badge_json() must never grow a
# key outside this set.
_SHIELDS_ENDPOINT_KEYS = {
    "schemaVersion",
    "label",
    "message",
    "color",
    "labelColor",
    "isError",
    "namedLogo",
    "logoSvg",
    "logoColor",
    "logoSize",
    "style",
    "cacheSeconds",
}


def test_badge_json_shape():
    grade = compute_grade(_violations(warnings=2, info=3), content_tokens=20_000)
    payload = grade.badge_json()
    assert payload["schemaVersion"] == 1
    assert payload["label"] == "skillsaw"
    assert payload["message"] == grade.letter
    assert payload["color"] == grade.color
    assert payload["logoSvg"].startswith("<svg")
    assert set(payload) <= _SHIELDS_ENDPOINT_KEYS


# ── CLI integration ──────────────────────────────────────────────


def test_lint_json_includes_grade(tmp_path):
    repo = copy_fixture("single-plugin/clean", tmp_path)
    r = run_lint(repo)
    grade = summary(r)["grade"]
    assert grade["letter"] == "A+"
    assert grade["content_tokens"] > 0
    assert grade["density"] >= 0


def test_lint_text_shows_grade(tmp_path):
    repo = copy_fixture("single-plugin/clean", tmp_path)
    r = run_lint(repo, fmt="text")
    assert "Grade:" in r["stdout"]
    assert "A+" in r["stdout"]


def test_lint_text_hints_at_hidden_info_violations(tmp_path):
    # The clean fixture has info-level violations that affect the grade
    # but are hidden without -v — the summary must say so.
    repo = copy_fixture("single-plugin/clean", tmp_path)
    quiet = run_lint(repo, fmt="text", verbose=False)
    assert "count toward the grade" in quiet["stdout"]
    assert "run with -v" in quiet["stdout"]

    # With -v the info list is already shown; no hint needed.
    loud = run_lint(repo, fmt="text", verbose=True)
    assert "run with -v" not in loud["stdout"]


def run_badge(path, *extra_args):
    result = subprocess.run(
        [sys.executable, "-m", "skillsaw", "badge", str(path), *extra_args],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result


def test_badge_writes_shields_json(tmp_path):
    repo = copy_fixture("single-plugin/clean", tmp_path)
    result = run_badge(repo)
    assert result.returncode == 0, result.stderr

    badge_file = repo / ".skillsaw-badge.json"
    assert badge_file.exists()
    payload = json.loads(badge_file.read_text())
    assert payload["schemaVersion"] == 1
    assert payload["message"] == "A+"
    assert payload["color"] == "brightgreen"
    assert set(payload) <= _SHIELDS_ENDPOINT_KEYS

    # README markdown for both shields.io badge styles, linking to skillsaw.org
    assert "img.shields.io/badge/dynamic/json" in result.stdout
    assert "query=%24.message" in result.stdout
    assert "img.shields.io/endpoint" in result.stdout
    assert "(https://skillsaw.org/)" in result.stdout
    # Saw-blade logo: embedded in the dynamic badge URL (endpoint badges get
    # it from the logoSvg field in the JSON payload instead)
    assert "logo=data%3Aimage%2Fsvg%2Bxml%3Bbase64%2C" in result.stdout


def test_badge_uses_github_remote_for_url(tmp_path):
    repo = copy_fixture("single-plugin/clean", tmp_path)
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "remote",
            "add",
            "origin",
            "git@github.com:example/clean-plugin.git",
        ],
        check=True,
    )
    result = run_badge(repo)
    assert result.returncode == 0, result.stderr
    assert (
        "raw.githubusercontent.com%2Fexample%2Fclean-plugin%2Fmain%2F.skillsaw-badge.json"
        in result.stdout
    )


def test_badge_without_remote_prints_placeholder(tmp_path):
    repo = copy_fixture("single-plugin/clean", tmp_path)
    result = run_badge(repo)
    assert result.returncode == 0, result.stderr
    assert "RAW_URL_TO_YOUR_BADGE_JSON" in result.stdout


def test_badge_custom_output_path(tmp_path):
    repo = copy_fixture("single-plugin/clean", tmp_path)
    out = tmp_path / "out" / "badge.json"
    result = run_badge(repo, "-o", str(out))
    assert result.returncode == 0, result.stderr
    assert json.loads(out.read_text())["schemaVersion"] == 1


def test_badge_ignores_baseline(tmp_path):
    repo = copy_fixture("single-plugin/broken", tmp_path)

    # Baseline away every violation: lint goes green...
    subprocess.run(
        [sys.executable, "-m", "skillsaw", "baseline", str(repo)],
        capture_output=True,
        check=True,
        timeout=60,
    )
    r = run_lint(repo)
    assert summary(r)["errors"] == 0

    # ...but the published badge still reflects the real state. The repo
    # has errors, so the error knockdown caps it at B+ or worse.
    result = run_badge(repo)
    assert result.returncode == 0, result.stderr
    payload = json.loads((repo / ".skillsaw-badge.json").read_text())
    assert payload["message"][0] != "A"


def test_badge_missing_path_errors():
    result = run_badge("/nonexistent/path")
    assert result.returncode == 1
    assert "Path not found" in result.stderr

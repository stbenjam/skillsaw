"""
Tests for the SVG report card (skillsaw.card) and the
``skillsaw badge --card`` subcommand.
"""

import subprocess
import xml.etree.ElementTree as ET

import pytest

import skillsaw.grade as grade_mod
from skillsaw.card import CARD_HEIGHT, CARD_WIDTH, SHIELDS_COLOR_HEX, THEMES, render_card
from skillsaw.grade import compute_grade
from skillsaw.rule import RuleViolation, Severity

from .test_grade import run_badge
from .test_integration import copy_fixture

_SVG_NS = "http://www.w3.org/2000/svg"


def _violations(errors=0, warnings=0, info=0):
    out = []
    for i in range(errors):
        out.append(RuleViolation("test-error", Severity.ERROR, f"error {i}"))
    for i in range(warnings):
        out.append(RuleViolation("test-warning", Severity.WARNING, f"warning {i}"))
    for i in range(info):
        out.append(RuleViolation("test-info", Severity.INFO, f"info {i}"))
    return out


def _render(**overrides):
    kwargs = dict(
        grade=compute_grade(_violations(warnings=5, info=3), content_tokens=12_345),
        repo_name="example/repo",
        plugin_count=3,
        skill_count=12,
        top_rules=[("content-vague", 5), ("skill-frontmatter", 3)],
        theme="light",
    )
    kwargs.update(overrides)
    return render_card(**kwargs)


def _texts_by_testid(svg):
    root = ET.fromstring(svg)
    found = {}
    for el in root.iter():
        testid = el.get("data-testid")
        if testid is not None:
            found[testid] = "".join(el.itertext())
    return found


# ── Rendering ────────────────────────────────────────────────────


def test_card_is_valid_xml_with_fixed_viewbox():
    svg = _render()
    root = ET.fromstring(svg)
    assert root.tag == f"{{{_SVG_NS}}}svg"
    assert root.get("viewBox") == f"0 0 {CARD_WIDTH} {CARD_HEIGHT}"
    assert root.get("width") == str(CARD_WIDTH)
    assert root.get("height") == str(CARD_HEIGHT)


def test_card_shows_grade_and_stats():
    grade = compute_grade(_violations(warnings=5, info=3), content_tokens=12_345)
    svg = _render(grade=grade)
    fields = _texts_by_testid(svg)
    assert fields["grade-letter"] == grade.letter
    assert fields["repo-name"] == "example/repo"
    assert fields["density"] == f"{grade.density:.2f}"
    assert fields["tokens"] == "12,345"
    assert fields["plugins"] == "3"
    assert fields["skills"] == "12"
    assert fields["rule-0"] == "1. content-vague (5)"
    assert fields["rule-1"] == "2. skill-frontmatter (3)"


def test_card_letter_is_color_graded():
    a_plus = _render(grade=compute_grade([], content_tokens=10_000))
    assert SHIELDS_COLOR_HEX["brightgreen"] in a_plus
    failing = _render(grade=compute_grade(_violations(errors=30, warnings=200), 1_000))
    assert SHIELDS_COLOR_HEX["red"] in failing
    assert SHIELDS_COLOR_HEX["brightgreen"] not in failing


def test_every_grade_color_has_a_hex_mapping():
    # Grade.color yields shields.io color names; the card must be able to
    # render every letter on the fixed scale.
    for letter in grade_mod.LETTER_NOTCHES:
        color = grade_mod._LETTER_COLORS[letter[0]]
        assert color in SHIELDS_COLOR_HEX


def test_card_is_byte_deterministic():
    assert _render() == _render()
    assert _render(theme="dark") == _render(theme="dark")


def test_card_has_no_network_references():
    # Offline guard: the only URL allowed in the output is the SVG xmlns
    # namespace *identifier* (required for <img> rendering, never fetched).
    # No external fonts, images, stylesheets, or scripts.
    for theme in THEMES:
        svg = _render(theme=theme)
        stripped = svg.replace(f'xmlns="{_SVG_NS}"', "")
        assert "http://" not in stripped
        assert "https://" not in stripped
        assert "@import" not in svg
        assert "<image" not in svg
        assert "<script" not in svg


def test_card_themes():
    light = _render(theme="light")
    dark = _render(theme="dark")
    assert light != dark
    assert THEMES["light"]["bg"] in light
    assert THEMES["dark"]["bg"] in dark
    ET.fromstring(light)
    ET.fromstring(dark)


def test_default_theme_is_dark():
    kwargs = dict(
        grade=compute_grade(_violations(warnings=5, info=3), content_tokens=12_345),
        repo_name="example/repo",
        plugin_count=3,
        skill_count=12,
        top_rules=[("content-vague", 5)],
    )
    assert THEMES["dark"]["bg"] in render_card(**kwargs)


def test_card_rejects_unknown_theme():
    with pytest.raises(ValueError, match="unknown theme"):
        _render(theme="solarized")


def test_card_escapes_repo_name():
    svg = _render(repo_name='<evil>&"repo"')
    fields = _texts_by_testid(svg)  # ET.fromstring implies well-formed XML
    assert fields["repo-name"] == '<evil>&"repo"'
    assert "<evil>" not in svg


def test_card_truncates_long_names():
    svg = _render(repo_name="x" * 100, top_rules=[("y" * 100, 1)])
    fields = _texts_by_testid(svg)
    assert len(fields["repo-name"]) <= 30
    assert fields["repo-name"].endswith("…")
    assert len(fields["rule-0"]) < 50


def test_card_without_violations_shows_clean_run():
    svg = _render(grade=compute_grade([], content_tokens=10_000), top_rules=[])
    fields = _texts_by_testid(svg)
    assert "rule-0" not in fields
    assert "clean run" in fields["rule-none"]


def test_card_shows_at_most_three_rules():
    svg = _render(top_rules=[(f"rule-{i}", 9 - i) for i in range(6)])
    fields = _texts_by_testid(svg)
    assert "rule-2" in fields
    assert "rule-3" not in fields


def test_card_empty_repo_name_falls_back():
    fields = _texts_by_testid(_render(repo_name=""))
    assert fields["repo-name"] == "repository"


def test_card_survives_off_scale_grade():
    # render_card is a public function: an unexpected letter or color
    # must not crash it. Unknown letters draw the empty (last-notch)
    # ring and a neutral accent.
    class _StubGrade:
        letter = "E"
        density = 3.0
        content_tokens = 1_000
        color = "papayawhip"

    svg = _render(grade=_StubGrade())
    fields = _texts_by_testid(svg)
    assert fields["grade-letter"] == "E"
    assert "#888888" in svg
    assert 'stroke-dasharray="0.00' in svg


# ── CLI integration ──────────────────────────────────────────────


def test_badge_card_writes_svg(tmp_path):
    repo = copy_fixture("marketplace/clean", tmp_path)
    result = run_badge(repo, "--card")
    assert result.returncode == 0, result.stderr

    # Badge JSON is still written as before.
    assert (repo / ".skillsaw-badge.json").exists()

    card_file = repo / ".skillsaw-card.svg"
    assert card_file.exists()
    svg = card_file.read_text(encoding="utf-8")
    fields = _texts_by_testid(svg)
    # marketplace/clean has 3 plugins and 2 skills.
    assert fields["plugins"] == "3"
    assert fields["skills"] == "2"
    assert fields["grade-letter"]
    assert fields["repo-name"] == repo.name

    # Dark theme is the default.
    assert THEMES["dark"]["bg"] in svg

    assert "Card written to" in result.stdout
    assert ".skillsaw-card.svg" in result.stdout
    # Ready-to-paste README markdown for the card.
    assert "[![skillsaw report card](" in result.stdout


def test_badge_card_light_theme(tmp_path):
    repo = copy_fixture("marketplace/clean", tmp_path)
    result = run_badge(repo, "--card", "--theme", "light")
    assert result.returncode == 0, result.stderr
    svg = (repo / ".skillsaw-card.svg").read_text(encoding="utf-8")
    assert THEMES["light"]["bg"] in svg
    ET.fromstring(svg)


def test_badge_card_beside_custom_output(tmp_path):
    repo = copy_fixture("marketplace/clean", tmp_path)
    out = tmp_path / "artifacts" / "badge.json"
    result = run_badge(repo, "--card", "-o", str(out))
    assert result.returncode == 0, result.stderr
    assert out.exists()
    card = tmp_path / "artifacts" / ".skillsaw-card.svg"
    assert card.exists()
    ET.fromstring(card.read_text(encoding="utf-8"))


def test_badge_card_uses_github_remote_for_url(tmp_path):
    repo = copy_fixture("marketplace/clean", tmp_path)
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "remote",
            "add",
            "origin",
            "git@github.com:example/market.git",
        ],
        check=True,
    )
    result = run_badge(repo, "--card")
    assert result.returncode == 0, result.stderr
    assert "raw.githubusercontent.com/example/market/main/.skillsaw-card.svg" in result.stdout


def test_badge_without_card_is_unchanged(tmp_path):
    # Without --card the command must behave exactly as before: same
    # output text, no SVG file.
    repo = copy_fixture("marketplace/clean", tmp_path)
    result = run_badge(repo)
    assert result.returncode == 0, result.stderr
    assert not (repo / ".skillsaw-card.svg").exists()
    assert "Card written" not in result.stdout
    assert "report card" not in result.stdout
    assert "Commit .skillsaw-badge.json and regenerate it" in result.stdout


# ── In-process CLI (coverage of the _run_badge paths the subprocess
#    integration tests above exercise outside the coverage tracer) ───


def run_badge_in_process(*argv):
    from skillsaw.cli._badge import _run_badge
    from skillsaw.cli._parser import _build_parser

    args = _build_parser().parse_args(["badge", *[str(a) for a in argv]])
    with pytest.raises(SystemExit) as exc:
        _run_badge(args)
    return exc.value.code


def test_run_badge_in_process_with_card(tmp_path, capsys):
    repo = copy_fixture("marketplace/clean", tmp_path)
    assert run_badge_in_process(repo, "--card") == 0
    out = capsys.readouterr().out

    svg = (repo / ".skillsaw-card.svg").read_text(encoding="utf-8")
    assert THEMES["dark"]["bg"] in svg  # default theme
    ET.fromstring(svg)

    # No git remote: the embed markdown falls back to placeholders.
    assert "RAW_URL_TO_YOUR_CARD_SVG" in out
    assert "Commit .skillsaw-badge.json and .skillsaw-card.svg" in out
    assert "camo" in out


def test_run_badge_in_process_with_remote(tmp_path, capsys):
    repo = copy_fixture("marketplace/clean", tmp_path)
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "remote", "add", "origin", "git@github.com:acme/mkt.git"],
        check=True,
    )
    assert run_badge_in_process(repo, "--card", "--theme", "light") == 0
    out = capsys.readouterr().out
    assert "raw.githubusercontent.com/acme/mkt/main/.skillsaw-card.svg" in out
    svg = (repo / ".skillsaw-card.svg").read_text(encoding="utf-8")
    assert THEMES["light"]["bg"] in svg
    # The card shows the remote's repo basename, not the checkout dirname.
    assert _texts_by_testid(svg)["repo-name"] == "mkt"


def test_repo_display_name(tmp_path):
    from skillsaw.cli._badge import _repo_display_name

    repo = tmp_path / "checkout-dir"
    repo.mkdir()
    # Not a git repo, then a repo without a remote: directory name.
    assert _repo_display_name(repo) == "checkout-dir"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    assert _repo_display_name(repo) == "checkout-dir"

    def set_url(url):
        subprocess.run(["git", "-C", str(repo), "remote", "remove", "origin"], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", url], check=True)

    set_url("https://github.com/acme/widgets.git")
    assert _repo_display_name(repo) == "widgets"
    set_url("git@github.com:acme/gadgets.git")
    assert _repo_display_name(repo) == "gadgets"
    set_url("https://gitlab.com/group/subgroup/tools/")
    assert _repo_display_name(repo) == "tools"


def test_run_badge_in_process_non_github_remote(tmp_path, capsys):
    repo = copy_fixture("marketplace/clean", tmp_path)
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "remote", "add", "origin", "https://gitlab.com/acme/mkt.git"],
        check=True,
    )
    assert run_badge_in_process(repo, "--card") == 0
    out = capsys.readouterr().out
    assert "RAW_URL_TO_YOUR_CARD_SVG" in out


def test_run_badge_in_process_without_card(tmp_path, capsys):
    repo = copy_fixture("marketplace/clean", tmp_path)
    assert run_badge_in_process(repo) == 0
    out = capsys.readouterr().out
    assert not (repo / ".skillsaw-card.svg").exists()
    assert "Commit .skillsaw-badge.json and regenerate it" in out


def test_run_badge_in_process_missing_path(capsys):
    assert run_badge_in_process("/nonexistent/repo/path", "--card") == 1
    assert "Path not found" in capsys.readouterr().err

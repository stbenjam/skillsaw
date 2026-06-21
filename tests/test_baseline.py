"""Unit tests for skillsaw.baseline."""

import hashlib
import json
from pathlib import Path

import pytest

from skillsaw.baseline import (
    BaselineEntry,
    BaselineFile,
    build_baseline,
    filter_baselined_violations,
    find_baseline,
    fingerprint_violation,
    load_baseline,
    save_baseline,
    BASELINE_FILENAME,
)
from skillsaw.rule import RuleViolation, Severity


def _make_violation(
    rule_id="test-rule",
    message="test message",
    file_path=None,
    line=None,
    severity=Severity.WARNING,
):
    return RuleViolation(
        rule_id=rule_id,
        severity=severity,
        message=message,
        file_path=file_path,
        line=line,
    )


class TestFingerprint:
    def test_deterministic(self, tmp_path):
        src = tmp_path / "CLAUDE.md"
        src.write_text("line one\nline two\nline three\n")
        v = _make_violation(file_path=src, line=2)
        fp1 = fingerprint_violation(v, tmp_path)
        fp2 = fingerprint_violation(v, tmp_path)
        assert fp1 == fp2
        assert len(fp1) == 16

    def test_survives_line_drift(self, tmp_path):
        src = tmp_path / "CLAUDE.md"
        src.write_text("line one\nline two\nline three\n")
        v1 = _make_violation(file_path=src, line=2)
        fp1 = fingerprint_violation(v1, tmp_path)

        src.write_text("inserted\nline one\nline two\nline three\n")
        v2 = _make_violation(file_path=src, line=3)
        fp2 = fingerprint_violation(v2, tmp_path)

        assert fp1 == fp2

    def test_different_content_different_hash(self, tmp_path):
        src = tmp_path / "CLAUDE.md"
        src.write_text("line one\nline two\n")
        v1 = _make_violation(file_path=src, line=1)
        fp1 = fingerprint_violation(v1, tmp_path)

        v2 = _make_violation(file_path=src, line=2)
        fp2 = fingerprint_violation(v2, tmp_path)

        assert fp1 != fp2

    def test_strips_whitespace(self, tmp_path):
        src = tmp_path / "CLAUDE.md"
        src.write_text("  hello world  \n")
        v1 = _make_violation(file_path=src, line=1)
        fp1 = fingerprint_violation(v1, tmp_path)

        src.write_text("hello world\n")
        v2 = _make_violation(file_path=src, line=1)
        fp2 = fingerprint_violation(v2, tmp_path)

        assert fp1 == fp2

    def test_without_line(self, tmp_path):
        src = tmp_path / "CLAUDE.md"
        src.write_text("content\n")
        v = _make_violation(file_path=src, line=None)
        fp = fingerprint_violation(v, tmp_path)
        assert len(fp) == 16

    def test_without_file(self, tmp_path):
        v = _make_violation(file_path=None, line=None)
        fp = fingerprint_violation(v, tmp_path)
        assert len(fp) == 16

    def test_file_not_found_fallback(self, tmp_path):
        missing = tmp_path / "gone.md"
        v = _make_violation(file_path=missing, line=1)
        fp = fingerprint_violation(v, tmp_path)
        assert len(fp) == 16

    def test_line_out_of_range_fallback(self, tmp_path):
        src = tmp_path / "CLAUDE.md"
        src.write_text("one line\n")
        v = _make_violation(file_path=src, line=999)
        fp = fingerprint_violation(v, tmp_path)
        assert len(fp) == 16

    def test_different_rules_different_hash(self, tmp_path):
        src = tmp_path / "CLAUDE.md"
        src.write_text("line one\n")
        v1 = _make_violation(rule_id="rule-a", file_path=src, line=1)
        v2 = _make_violation(rule_id="rule-b", file_path=src, line=1)
        assert fingerprint_violation(v1, tmp_path) != fingerprint_violation(v2, tmp_path)


class TestBaselineIO:
    def test_save_and_load_roundtrip(self, tmp_path):
        entries = [
            BaselineEntry(
                fingerprint="abc123",
                rule_id="test-rule",
                file_path="CLAUDE.md",
                line=10,
                message="test message",
                severity="warning",
            )
        ]
        bf = BaselineFile(
            version="1",
            generated_by="skillsaw test",
            generated_at="2025-01-01T00:00:00+00:00",
            violations=entries,
        )
        path = tmp_path / BASELINE_FILENAME
        save_baseline(path, bf)
        loaded = load_baseline(path)

        assert loaded.version == bf.version
        assert loaded.generated_by == bf.generated_by
        assert len(loaded.violations) == 1
        assert loaded.violations[0].fingerprint == "abc123"
        assert loaded.violations[0].rule_id == "test-rule"

    def test_load_invalid_json(self, tmp_path):
        path = tmp_path / BASELINE_FILENAME
        path.write_text("not json{{{")
        with pytest.raises(ValueError, match="Invalid baseline JSON"):
            load_baseline(path)

    def test_load_wrong_version(self, tmp_path):
        path = tmp_path / BASELINE_FILENAME
        path.write_text(json.dumps({"version": "99", "violations": []}))
        with pytest.raises(ValueError, match="Unsupported baseline version"):
            load_baseline(path)

    def test_load_missing_fingerprint(self, tmp_path):
        path = tmp_path / BASELINE_FILENAME
        data = {"version": "1", "violations": [{"rule_id": "r", "message": "m"}]}
        path.write_text(json.dumps(data))
        with pytest.raises(ValueError, match="missing required 'fingerprint'"):
            load_baseline(path)

    def test_save_format(self, tmp_path):
        bf = BaselineFile(
            version="1",
            generated_by="skillsaw 0.10.1",
            generated_at="2025-01-01T00:00:00+00:00",
            violations=[],
        )
        path = tmp_path / BASELINE_FILENAME
        save_baseline(path, bf)
        data = json.loads(path.read_text())
        assert data["version"] == "1"
        assert data["generated_by"] == "skillsaw 0.10.1"
        assert data["violations"] == []


class TestFilterBaselinedViolations:
    def _baseline_with(self, entries):
        return BaselineFile(
            version="1",
            generated_by="test",
            generated_at="2025-01-01T00:00:00+00:00",
            violations=entries,
        )

    def test_removes_baselined_violations(self, tmp_path):
        src = tmp_path / "CLAUDE.md"
        src.write_text("try to do something\n")
        v = _make_violation(rule_id="weak", file_path=src, line=1)
        fp = fingerprint_violation(v, tmp_path)

        baseline = self._baseline_with(
            [
                BaselineEntry(
                    fingerprint=fp,
                    rule_id="weak",
                    file_path="CLAUDE.md",
                    line=1,
                    message="test",
                    severity="warning",
                )
            ]
        )

        kept, stale = filter_baselined_violations([v], baseline, tmp_path)
        assert len(kept) == 0
        assert len(stale) == 0

    def test_keeps_new_violations(self, tmp_path):
        src = tmp_path / "CLAUDE.md"
        src.write_text("try to do something\n")
        v = _make_violation(rule_id="weak", file_path=src, line=1)

        baseline = self._baseline_with(
            [
                BaselineEntry(
                    fingerprint="different_fp",
                    rule_id="other-rule",
                    file_path="CLAUDE.md",
                    line=1,
                    message="other",
                    severity="warning",
                )
            ]
        )

        kept, stale = filter_baselined_violations([v], baseline, tmp_path)
        assert len(kept) == 1
        assert kept[0] is v

    def test_reports_stale_entries(self, tmp_path):
        baseline = self._baseline_with(
            [
                BaselineEntry(
                    fingerprint="stale_fp",
                    rule_id="old-rule",
                    file_path="CLAUDE.md",
                    line=5,
                    message="old issue",
                    severity="error",
                )
            ]
        )

        kept, stale = filter_baselined_violations([], baseline, tmp_path)
        assert len(kept) == 0
        assert len(stale) == 1
        assert stale[0].fingerprint == "stale_fp"

    def test_handles_duplicate_fingerprints(self, tmp_path):
        src = tmp_path / "CLAUDE.md"
        src.write_text("same line\nsame line\n")
        v1 = _make_violation(rule_id="r", file_path=src, line=1)
        v2 = _make_violation(rule_id="r", file_path=src, line=2)
        fp = fingerprint_violation(v1, tmp_path)
        assert fp == fingerprint_violation(v2, tmp_path)

        baseline = self._baseline_with(
            [
                BaselineEntry(
                    fingerprint=fp,
                    rule_id="r",
                    file_path="CLAUDE.md",
                    line=1,
                    message="",
                    severity="warning",
                ),
            ]
        )

        kept, stale = filter_baselined_violations([v1, v2], baseline, tmp_path)
        assert len(kept) == 1
        assert len(stale) == 0

    def test_empty_baseline(self, tmp_path):
        v = _make_violation()
        baseline = self._baseline_with([])
        kept, stale = filter_baselined_violations([v], baseline, tmp_path)
        assert len(kept) == 1
        assert len(stale) == 0

    def test_empty_violations(self, tmp_path):
        baseline = self._baseline_with(
            [
                BaselineEntry(
                    fingerprint="fp",
                    rule_id="r",
                    file_path="f.md",
                    line=1,
                    message="m",
                    severity="warning",
                ),
            ]
        )
        kept, stale = filter_baselined_violations([], baseline, tmp_path)
        assert len(kept) == 0
        assert len(stale) == 1


class TestRatchetBaseline:
    def _baseline_with(self, entries):
        return BaselineFile(
            version="1",
            generated_by="test",
            generated_at="2025-01-01T00:00:00+00:00",
            violations=entries,
        )

    def _ratchet_entry(self, value, mode, rule_id="context-budget", file_path="CLAUDE.md"):
        fp = hashlib.sha256(f"{rule_id}\0{file_path}".encode()).hexdigest()[:16]
        return BaselineEntry(
            fingerprint=fp,
            rule_id=rule_id,
            file_path=file_path,
            line=None,
            message="test",
            severity="warning",
            value=value,
            baseline_mode=mode,
        )

    def _ratchet_violation(self, value, tmp_path, rule_id="context-budget"):
        src = tmp_path / "CLAUDE.md"
        if not src.exists():
            src.write_text("content\n")
        return _make_violation(rule_id=rule_id, file_path=src, line=None, message=f"value={value}")

    def test_ceiling_improved_suppressed(self, tmp_path):
        entry = self._ratchet_entry(5000, "ceiling")
        baseline = self._baseline_with([entry])
        v = self._ratchet_violation(4800, tmp_path)
        v.value = 4800
        kept, stale = filter_baselined_violations([v], baseline, tmp_path)
        assert len(kept) == 0

    def test_ceiling_worsened_reported(self, tmp_path):
        entry = self._ratchet_entry(5000, "ceiling")
        baseline = self._baseline_with([entry])
        v = self._ratchet_violation(5200, tmp_path)
        v.value = 5200
        kept, stale = filter_baselined_violations([v], baseline, tmp_path)
        assert len(kept) == 1
        assert stale == []

    def test_floor_improved_suppressed(self, tmp_path):
        entry = self._ratchet_entry(30, "floor")
        baseline = self._baseline_with([entry])
        v = self._ratchet_violation(35, tmp_path)
        v.value = 35
        kept, stale = filter_baselined_violations([v], baseline, tmp_path)
        assert len(kept) == 0

    def test_floor_worsened_reported(self, tmp_path):
        entry = self._ratchet_entry(30, "floor")
        baseline = self._baseline_with([entry])
        v = self._ratchet_violation(25, tmp_path)
        v.value = 25
        kept, stale = filter_baselined_violations([v], baseline, tmp_path)
        assert len(kept) == 1
        assert stale == []

    def test_ratchet_worsened_not_reported_stale(self, tmp_path):
        """Regression for issue #258 (Bug B): a ratchet entry whose value
        regressed past the baseline must be kept as a violation but never
        also reported stale — a stale report prompts `skillsaw baseline`,
        which would rebaseline the regressed value and defeat the ratchet."""
        entry = self._ratchet_entry(100, "ceiling")
        baseline = self._baseline_with([entry])
        v = self._ratchet_violation(200, tmp_path)
        v.value = 200
        kept, stale = filter_baselined_violations([v], baseline, tmp_path)
        assert len(kept) == 1
        assert stale == []

    def test_ratchet_equal_suppressed(self, tmp_path):
        entry = self._ratchet_entry(5000, "ceiling")
        baseline = self._baseline_with([entry])
        v = self._ratchet_violation(5000, tmp_path)
        v.value = 5000
        kept, stale = filter_baselined_violations([v], baseline, tmp_path)
        assert len(kept) == 0

    def test_ratchet_stale_when_violation_gone(self, tmp_path):
        entry = self._ratchet_entry(5000, "ceiling")
        baseline = self._baseline_with([entry])
        kept, stale = filter_baselined_violations([], baseline, tmp_path)
        assert len(stale) == 1

    def test_ratchet_fingerprint_stable_across_values(self, tmp_path):
        src = tmp_path / "CLAUDE.md"
        src.write_text("content\n")
        v1 = _make_violation(rule_id="context-budget", file_path=src, message="5000 tokens")
        v1.value = 5000
        v2 = _make_violation(rule_id="context-budget", file_path=src, message="4800 tokens")
        v2.value = 4800
        fp1 = fingerprint_violation(v1, tmp_path)
        fp2 = fingerprint_violation(v2, tmp_path)
        assert fp1 == fp2


class TestFindBaseline:
    def test_finds_in_directory(self, tmp_path):
        bf = tmp_path / BASELINE_FILENAME
        bf.write_text("{}")
        assert find_baseline(tmp_path) == bf

    def test_finds_in_parent(self, tmp_path):
        bf = tmp_path / BASELINE_FILENAME
        bf.write_text("{}")
        child = tmp_path / "sub" / "dir"
        child.mkdir(parents=True)
        assert find_baseline(child) == bf

    def test_not_found(self, tmp_path):
        assert find_baseline(tmp_path) is None


class TestRatchetMetricDiscriminator:
    """Regression: two ratchet violations on one file must not collide (§1.11)."""

    def _v(self, tmp_path, value, metric=None, line=None):
        src = tmp_path / "SKILL.md"
        if not src.exists():
            src.write_text("content\n")
        v = _make_violation(
            rule_id="context-budget", file_path=src, line=line, message=f"value={value}"
        )
        v.value = value
        v.metric = metric
        return v

    def test_metric_distinguishes_fingerprints(self, tmp_path):
        # The whole-file violation stays metric-less (legacy fingerprint); only
        # the description carries a metric. They must not collide.
        file_v = self._v(tmp_path, 5000, metric=None)
        desc_v = self._v(tmp_path, 80, metric="skill-description", line=2)
        assert fingerprint_violation(file_v, tmp_path) != fingerprint_violation(desc_v, tmp_path)

    def test_whole_file_keeps_legacy_fingerprint(self, tmp_path):
        """Backward-compat: the whole-file ratchet fingerprint is unchanged so a
        pre-upgrade baseline keeps matching after the metric was added."""
        file_v = self._v(tmp_path, 5000, metric=None)
        legacy = hashlib.sha256(b"context-budget\0SKILL.md").hexdigest()[:16]
        assert fingerprint_violation(file_v, tmp_path) == legacy

    def test_no_metric_keeps_legacy_fingerprint(self, tmp_path):
        """Backward-compat: an empty metric must not change the fingerprint."""
        v = self._v(tmp_path, 5000, metric=None)
        rel = "SKILL.md"
        legacy = hashlib.sha256(f"context-budget\0{rel}".encode()).hexdigest()[:16]
        assert fingerprint_violation(v, tmp_path) == legacy

    def test_both_metrics_ratchet_independently(self, tmp_path):
        """A regression in one metric is not masked by the other's baseline."""
        # Whole-file entry: legacy (metric-less) fingerprint.
        file_entry = BaselineEntry(
            fingerprint=hashlib.sha256(b"context-budget\0SKILL.md").hexdigest()[:16],
            rule_id="context-budget",
            file_path="SKILL.md",
            line=None,
            message="file",
            severity="warning",
            value=5000,
            baseline_mode="ceiling",
        )
        # Description entry: metric-tagged fingerprint.
        desc_entry = BaselineEntry(
            fingerprint=hashlib.sha256(b"context-budget\0SKILL.md\0skill-description").hexdigest()[
                :16
            ],
            rule_id="context-budget",
            file_path="SKILL.md",
            line=None,
            message="desc",
            severity="warning",
            value=80,
            baseline_mode="ceiling",
        )
        baseline = BaselineFile(
            version="1",
            generated_by="test",
            generated_at="2025-01-01T00:00:00+00:00",
            violations=[file_entry, desc_entry],
        )
        # Whole-file improved (suppressed), description regressed (kept).
        file_v = self._v(tmp_path, 4800, metric=None)
        desc_v = self._v(tmp_path, 120, metric="skill-description", line=2)
        kept, stale = filter_baselined_violations([file_v, desc_v], baseline, tmp_path)
        assert len(kept) == 1
        assert kept[0].metric == "skill-description"
        assert stale == []


class TestBaselineRootStability:
    """Regression: a baseline matches when lint runs from a subdirectory (§1.3)."""

    def test_fingerprint_relative_to_baseline_root(self, tmp_path):
        # Baseline built at the repo root over skills/s/SKILL.md.
        skill = tmp_path / "skills" / "s"
        skill.mkdir(parents=True)
        src = skill / "SKILL.md"
        src.write_text("You should probably try to do it\n")
        v = _make_violation(rule_id="weak", file_path=src, line=1, message="weak")
        built = build_baseline([v], tmp_path, "0.14.0")
        assert built.violations[0].file_path == "skills/s/SKILL.md"
        assert built.root_path == tmp_path.resolve()

        lint_subdir = tmp_path / "skills" / "s"
        kept, stale = filter_baselined_violations([v], built, lint_subdir)
        assert kept == []
        assert stale == []

        baseline_path = tmp_path / BASELINE_FILENAME
        save_baseline(baseline_path, built)
        loaded = load_baseline(baseline_path)
        assert loaded.root_path == tmp_path.resolve()

        kept, stale = filter_baselined_violations([v], loaded, lint_subdir)
        assert kept == []
        assert stale == []


class TestBuildBaseline:
    def test_builds_from_violations(self, tmp_path):
        src = tmp_path / "CLAUDE.md"
        src.write_text("try to do something\nmaybe fix later\n")
        v1 = _make_violation(rule_id="weak", file_path=src, line=1, message="weak lang")
        v2 = _make_violation(rule_id="weak", file_path=src, line=2, message="weak lang 2")

        bf = build_baseline([v1, v2], tmp_path, "0.10.1")
        assert bf.version == "1"
        assert bf.generated_by == "skillsaw 0.10.1"
        assert len(bf.violations) == 2
        assert all(len(e.fingerprint) == 16 for e in bf.violations)
        assert bf.violations[0].rule_id == "weak"
        assert bf.violations[0].file_path == "CLAUDE.md"

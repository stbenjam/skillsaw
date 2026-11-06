#!/usr/bin/env python3
"""Compare skillsaw with ``claude plugin validate`` on the Claude fixtures.

Every directory under ``tests/fixtures/`` that holds a ``.claude-plugin/``
is validated twice: by Claude Code's own validator, which stands in for the
loader, and by ``skillsaw lint``. The results are compared with the manifest
in ``tests/claude_conformance.json``, which records for each fixture:

* ``official`` — what the validator says will not load: its errors, plus
  the warnings that say an entry or server is dropped at load time.
  Advisory warnings (missing author, unquoted paths) are not recorded.
* ``skillsaw`` — the rule ids skillsaw reports at error severity.
* ``note`` — why the two differ, required when exactly one side is empty.

Usage::

    scripts/claude-conformance.py            # check; exit 1 on drift
    scripts/claude-conformance.py --write    # re-record (keeps notes)
    scripts/claude-conformance.py --skillsaw-only

The validator half needs the ``claude`` CLI at the pinned version; see
docs/claude-validate.md.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
MANIFEST = ROOT / "tests" / "claude_conformance.json"

# Validator warnings that describe a load failure rather than advice.
_LOAD_DROP = re.compile(r"ignored at runtime|drops? this server|dropped at load")

LintFn = Callable[[Path], dict]


def fixture_dirs() -> List[str]:
    """Fixture directories, relative to tests/fixtures, that hold a .claude-plugin/."""
    return sorted(
        p.parent.relative_to(FIXTURES).as_posix()
        for p in FIXTURES.rglob(".claude-plugin")
        if p.is_dir()
    )


def claude_version(claude: str = "claude") -> Optional[str]:
    """The installed Claude Code version, or None when the CLI is absent."""
    path = shutil.which(claude)
    if path is None:
        return None
    out = subprocess.run([path, "--version"], capture_output=True, text=True, check=False)
    match = re.match(r"\s*(\d+\.\d+\.\d+)", out.stdout)
    return match.group(1) if match else None


def official_failures(fixture: str, claude: str = "claude") -> List[str]:
    """``file: path`` for each problem the validator says stops loading."""
    target = FIXTURES / fixture
    out = subprocess.run(
        [claude, "plugin", "validate", "--json", str(target)],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "DISABLE_AUTOUPDATER": "1"},
    )
    report = json.loads(out.stdout)
    found = set()
    for section in [report.get("manifest")] + list(report.get("contents") or []):
        if not section:
            continue
        rel = os.path.relpath(section.get("file", str(target)), target)
        for item in section.get("errors", []):
            found.add(f"{rel}: {item.get('path')}")
        for item in section.get("warnings", []):
            if _LOAD_DROP.search(item.get("message", "")):
                found.add(f"{rel}: {item.get('path')}")
    return sorted(found)


def _lint_subprocess(path: Path) -> dict:
    out = subprocess.run(
        [sys.executable, "-m", "skillsaw", "lint", "--format", "json", "--no-progress", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    return json.loads(out.stdout)


def skillsaw_errors(fixture: str, lint: LintFn = _lint_subprocess) -> List[str]:
    """Rule ids skillsaw reports at error severity on a copy of the fixture."""
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "repo"
        shutil.copytree(FIXTURES / fixture, copy, symlinks=True)
        report = lint(copy)
    return sorted({v["rule_id"] for v in report["violations"] if v["severity"] == "error"})


def load_manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def write_manifest(version: str, results: Dict[str, Dict[str, List[str]]]) -> None:
    old = load_manifest()["fixtures"] if MANIFEST.exists() else {}
    fixtures = {}
    for name in sorted(results):
        entry = dict(results[name])
        note = old.get(name, {}).get("note")
        if note:
            entry["note"] = note
        fixtures[name] = entry
    data = {"claude_code_version": version, "fixtures": fixtures}
    MANIFEST.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--write", action="store_true", help="re-record the manifest")
    parser.add_argument("--skillsaw-only", action="store_true", help="skip the validator")
    parser.add_argument("--claude", default="claude", help="claude executable")
    args = parser.parse_args()

    manifest = load_manifest() if MANIFEST.exists() else {"fixtures": {}}
    pinned = manifest.get("claude_code_version")
    version = None
    if not args.skillsaw_only:
        version = claude_version(args.claude)
        if version is None:
            print(f"error: '{args.claude}' not found; pass --skillsaw-only", file=sys.stderr)
            return 2
        if version != pinned and not args.write:
            print(f"error: manifest pins Claude Code {pinned}, found {version}", file=sys.stderr)
            return 2

    results: Dict[str, Dict[str, List[str]]] = {}
    drift = 0
    for fixture in fixture_dirs():
        recorded = manifest["fixtures"].get(fixture, {})
        actual = {
            "official": (
                recorded.get("official", [])
                if args.skillsaw_only
                else official_failures(fixture, args.claude)
            ),
            "skillsaw": skillsaw_errors(fixture),
        }
        results[fixture] = actual
        for side in ("official", "skillsaw"):
            if actual[side] != recorded.get(side):
                drift += 1
                print(f"{fixture}: {side} {recorded.get(side)} -> {actual[side]}")

    for stale in sorted(set(manifest["fixtures"]) - set(results)):
        drift += 1
        print(f"{stale}: recorded, but no such fixture")

    if args.write:
        write_manifest(version or pinned, results)
        print(f"wrote {MANIFEST.relative_to(ROOT)} ({len(results)} fixtures)")
        return 0
    if drift:
        print(f"{drift} difference(s) from {MANIFEST.relative_to(ROOT)}")
        return 1
    print(f"{len(results)} fixtures match {MANIFEST.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

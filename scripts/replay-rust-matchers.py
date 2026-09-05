"""Optional Rust-engine replay of literal matcher evidence; no host is invoked."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess


def main() -> int:
    rg = shutil.which("rg")
    if rg is None:
        raise SystemExit("Install ripgrep to run this optional evidence replay.")
    evidence = json.loads(
        (
            Path(__file__).resolve().parents[1] / "tests/fixtures/hooks/rust-matchers/evidence.json"
        ).read_text(encoding="utf-8")
    )
    version = subprocess.check_output([rg, "--version"], text=True).splitlines()[0]
    results = []
    for case in evidence["cases"]:
        result = subprocess.run(
            [rg, "--no-config", "--engine", "default", "-e", case["pattern"]],
            input=evidence["ripgrep"]["stdin"],
            text=True,
            capture_output=True,
            timeout=5,
        )
        if result.returncode in (0, 1):
            verdict = "accepted"
        elif result.returncode == 2 and "regex parse error:" in result.stderr:
            verdict = "refused"
        else:
            verdict = "unresolved"
        results.append(
            {
                "id": case["id"],
                "pattern": case["pattern"],
                "verdict": verdict,
                "expected": case["rust_verdict"],
                "exit": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        )
    print(json.dumps({"version": version, "results": results}, indent=2))
    return int(any(row["verdict"] != row["expected"] for row in results))


if __name__ == "__main__":
    raise SystemExit(main())

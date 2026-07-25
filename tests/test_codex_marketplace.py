"""Codex marketplace distribution metadata."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_codex_marketplace_exposes_the_root_skill_bundle() -> None:
    """Codex's documented selector must resolve to the root skill bundle."""
    marketplace = json.loads(
        (ROOT / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8")
    )
    manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))

    assert marketplace["name"] == "skillsaw-marketplace"
    plugin = next(item for item in marketplace["plugins"] if item["name"] == manifest["name"])
    assert plugin["source"] == {"source": "local", "path": "./"}
    assert plugin["policy"]["installation"] == "AVAILABLE"
    assert manifest["name"] == "skillsaw"
    assert manifest["skills"] == "./skills/"
    skills_dir = ROOT / manifest["skills"]
    assert skills_dir.is_dir()
    assert any(skills_dir.glob("*/SKILL.md"))

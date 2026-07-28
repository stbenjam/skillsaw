"""Shared helpers for the Codex rule tests.

Fixtures under ``tests/fixtures/codex/`` mirror layouts observed in real
Codex marketplaces (openai/plugins and community catalogs); the ``broken``
fixture reproduces divergences found there — ``..`` in a manifest path, a
stray ``hooks.json`` inside ``.codex-plugin/``, duplicate catalog names, a
dangling local source, and an unregistered plugin.
"""

import json
import shutil
from pathlib import Path

from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.codex import (
    CodexMarketplaceJsonValidRule,
    CodexMarketplaceRegistrationRule,
    CodexOpenAIMetadataRule,
    CodexPluginJsonValidRule,
    CodexPluginStructureRule,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

CODEX_RULES = [
    CodexMarketplaceJsonValidRule,
    CodexMarketplaceRegistrationRule,
    CodexPluginJsonValidRule,
    CodexPluginStructureRule,
    CodexOpenAIMetadataRule,
]


def copy_fixture(name, tmp_path):
    src = FIXTURES / name
    dst = tmp_path / name.replace("/", "_")
    # symlinks=True: a fixture that ships an escaping symlink is copied as
    # the symlink, not as the contents behind it — copying the contents
    # would rebuild the layout as an ordinary directory and quietly turn a
    # containment test into a no-op.
    shutil.copytree(src, dst, symlinks=True)
    return dst


def run_rule(rule_cls, repo_path, config=None):
    context = RepositoryContext(Path(repo_path))
    return rule_cls(config or {}).check(context)


def messages(violations):
    return [v.message for v in violations]


def by_severity(violations, severity):
    return [v for v in violations if v.severity is severity]


def _write_plugin(plugin_dir: Path, manifest: dict) -> Path:
    (plugin_dir / ".codex-plugin").mkdir(parents=True, exist_ok=True)
    (plugin_dir / ".codex-plugin" / "plugin.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return plugin_dir


def _codex_plugin_repo(tmp_path: Path, manifest: dict) -> Path:
    repo = tmp_path / "plugin-repo"
    repo.mkdir()
    return _write_plugin(repo, manifest)


def _codex_marketplace_repo(tmp_path: Path, marketplace: dict) -> Path:
    repo = tmp_path / "marketplace-repo"
    (repo / ".agents" / "plugins").mkdir(parents=True)
    (repo / ".agents" / "plugins" / "marketplace.json").write_text(
        json.dumps(marketplace, indent=2), encoding="utf-8"
    )
    return repo

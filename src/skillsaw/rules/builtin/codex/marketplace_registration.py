"""
Rule: codex-marketplace-registration
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from skillsaw.rule import (
    Rule,
    RuleViolation,
    Severity,
    AutofixResult,
    AutofixConfidence,
)
from skillsaw.context import RepositoryContext, codex_local_source_path, safe_resolve
from skillsaw.formats.codex import (
    codex_plugin_name,
    is_remote_source,
    safe_is_dir,
    safe_is_file,
)
from skillsaw.lint_target import CodexMarketplaceConfigNode, CodexPluginConfigNode
from skillsaw.rules.builtin.utils import read_json, read_text

from ._helpers import (
    CODEX_MARKETPLACE_REPO_TYPES,
    KEBAB_CASE,
    reject_nonfinite_json_number,
    safe_display,
)

# What ``fix()`` writes for a newly registered plugin. Every entry in the
# openai/plugins catalog carries these four keys, and the spec asks for
# policy.installation, policy.authentication and category on every entry.
_NEW_ENTRY_POLICY = {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}
_NEW_ENTRY_CATEGORY = "Productivity"


def _reject_duplicate_json_keys(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    """Build one JSON object, rejecting keys the decoder would collapse."""
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _mutable_marketplace_data(original: str) -> Optional[dict]:
    """Parse a marketplace manifest into a document ``fix()`` can extend.

    ``None`` when the file cannot be rewritten safely — unparseable JSON, a
    duplicate object key, a non-object root, or a non-list ``plugins`` key.
    codex-marketplace-json-valid reports malformed shapes; they need manual
    repair, so registration violations against them must not advertise
    fixability. Shared by ``check()`` (to decide ``fixable``) and ``fix()`` so
    the two cannot drift.
    """
    try:
        data = json.loads(
            original,
            parse_constant=reject_nonfinite_json_number,
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except (json.JSONDecodeError, ValueError):
        return None
    except RecursionError:
        # The shared reader turns this into an ordinary parse error, but
        # this reparses the raw text to keep ruamel out of the fix path.
        # Letting it escape makes the rule a rule-execution-error instead
        # of standing down on a catalog that is already invalid.
        return None
    if not isinstance(data, dict):
        return None
    if "plugins" in data and not isinstance(data["plugins"], list):
        return None
    return data


class CodexMarketplaceRegistrationRule(Rule):
    """Check that Codex marketplace entries and plugin directories agree"""

    autofix_confidence = AutofixConfidence.SUGGEST
    repo_types = CODEX_MARKETPLACE_REPO_TYPES
    since = "0.18.0"

    @property
    def rule_id(self) -> str:
        return "codex-marketplace-registration"

    @property
    def description(self) -> str:
        return "Codex plugins must be registered in .agents/plugins/marketplace.json"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        config_nodes = context.lint_tree.find(CodexMarketplaceConfigNode)
        if not config_nodes:
            return []

        violations: List[RuleViolation] = []
        registered_names, registered_dirs, local_names = self._registered(context)

        for node in config_nodes:
            violations.extend(self._check_entries(context, node.path))

        primary = config_nodes[0].path
        unregistered = self._unregistered(context, registered_names, registered_dirs)
        if not unregistered:
            return violations

        truly_unregistered = [(d, n) for d, n in unregistered if n not in local_names]
        registerable = self._registerable(context, truly_unregistered, primary)
        for plugin_dir, name in unregistered:
            if name in local_names:
                # The catalog lists the name but its local source path does
                # not resolve to this directory. "Not registered" would be
                # factually wrong — the name is right there — and fix()
                # skips this by design (appending a second entry for a
                # listed name would create a duplicate), so per the
                # invariant it must not be a hard ERROR either.
                violations.append(
                    self.violation(
                        f"Plugin '{safe_display(name)}' is listed in {primary.name} but the "
                        "entry's source path does not resolve to this "
                        "directory — fix the entry's path rather than "
                        "adding a second one",
                        file_path=primary,
                        severity=Severity.WARNING,
                        fixable=False,
                    )
                )
                continue
            violations.append(
                self.violation(
                    self._unregistered_message(name, primary),
                    file_path=primary,
                    fixable=registerable.get(name) == plugin_dir,
                )
            )

        return violations

    def _registerable(
        self,
        context: RepositoryContext,
        unregistered: List[Tuple[Path, str]],
        marketplace_file: Path,
    ) -> Dict[str, Path]:
        """name -> plugin directory for the entries ``fix()`` may safely add.

        Both ``check()`` and ``fix()`` go through this, because ``fixable``
        is only a display flag — the linter hands every *visible* violation
        to ``fix()`` regardless of it, so a guard applied in ``check()``
        alone does not actually stop the write.

        A plugin is excluded when:

        * two discovered directories declare its name — registering one
          would put that name in the catalog and silence the other's
          violation without making it installable, so the duplicate name is
          the bug to fix by hand;
        * its manifest declares no ``name`` and ``codex_plugin_name`` fell
          back to the directory name, which for a root-level plugin is
          whatever the checkout happens to be called (committing that would
          also introduce a fresh kebab-case violation);
        * it lies outside the marketplace root, where sources cannot reach
          it — ``..`` is not allowed in a source;
        * the catalog cannot be rewritten safely at all.
        """
        if _mutable_marketplace_data(_read_text(marketplace_file)) is None:
            return {}

        # Every name the catalog spells, local entries included. This is a
        # different question from ``_registered()``, which deliberately
        # ignores local entries' names — here the point is that ``fix()``
        # refuses to append a name already present, so advertising the fix
        # would offer a no-op that leaves the violation standing.
        catalog_names = {
            entry.get("name")
            for node in context.lint_tree.find(CodexMarketplaceConfigNode)
            for _, entry in _entries(node.path)
            if isinstance(entry.get("name"), str)
        }

        counts: Dict[str, int] = {}
        for _, name in unregistered:
            counts[name] = counts.get(name, 0) + 1

        registerable: Dict[str, Path] = {}
        for plugin_dir, name in unregistered:
            if counts[name] > 1 or name in catalog_names:
                continue
            if not self._has_declared_name(context, plugin_dir):
                continue
            if _relative_source(plugin_dir, context) is None:
                continue
            registerable[name] = plugin_dir
        return registerable

    @staticmethod
    def _unregistered_message(name: str, marketplace_file: Path) -> str:
        """The one place the unregistered-plugin message is spelled.

        ``fix()`` re-renders it to pair a plugin with its violation, so the
        two must not drift.
        """
        return f"Plugin '{safe_display(name)}' not registered in {marketplace_file.name}"

    @staticmethod
    def _has_declared_name(context: RepositoryContext, plugin_dir: Path) -> bool:
        """Whether the manifest names the plugin itself.

        ``codex_plugin_name`` falls back to the directory name, which for a
        root-level plugin is whatever the checkout happens to be called —
        a machine-dependent string the autofix must not commit. The missing
        field is codex-plugin-json-valid's to report.
        """
        manifest = _read_manifest(plugin_dir.joinpath(*context.CODEX_PLUGIN_MANIFEST))
        name = manifest.get("name")
        if not isinstance(name, str) or not name:
            return False
        # Writing a non-kebab name into the catalog trades one violation for
        # another: codex-marketplace-json-valid rejects it on the next run,
        # and the identifier hosts use as the component namespace is now
        # published. The manifest name has to be corrected by hand first.
        return bool(KEBAB_CASE.match(name))

    def _unregistered(
        self,
        context: RepositoryContext,
        registered_names: Set[str],
        registered_dirs: Set[Path],
    ) -> List[Tuple[Path, str]]:
        """Discovered plugin directories no catalog covers.

        Plugins under ``.codex/plugins/`` are skipped: that is where Codex
        installs third-party plugins into a developer's checkout, so they
        are not the repository's to publish. They stay discovered — their
        hooks and skills are still linted — but demanding the repository
        catalog them would fail the lint of anyone who installed one, and
        the autofix would write a third-party install into the published
        catalog.
        """
        found: List[Tuple[Path, str]] = []
        for plugin_node in context.lint_tree.find(CodexPluginConfigNode):
            plugin_dir = plugin_node.plugin_dir
            if not plugin_node.path.is_file():
                # A .codex-plugin/ directory with no manifest. There is
                # nothing installable to register, and codex-plugin-json-valid
                # already reports the missing entrypoint — stacking a second
                # error on it would just say the same defect twice.
                continue
            if plugin_dir.resolve() in registered_dirs:
                continue
            if context.is_codex_installed_plugin(plugin_dir):
                continue
            if context.is_path_excluded(plugin_node.path):
                # Registration files its violation against the catalog, not
                # the excluded manifest, so the linter's path filter cannot
                # enforce this boundary for us. Skipping here also keeps the
                # fixer from publishing an excluded plugin.
                continue
            name = codex_plugin_name(plugin_dir)
            if name in registered_names:
                continue
            found.append((plugin_dir, name))
        return found

    def _registered(self, context: RepositoryContext) -> Tuple[Set[str], Set[Path], Set[str]]:
        """Names and plugin directories the repository's catalogs already cover.

        A plugin counts as registered when *any* catalog names it — openai/
        plugins splits its catalog across two files — or when an entry's
        local source resolves to its directory. The second half matters
        because an entry whose ``name`` disagrees with the manifest still
        installs that directory; without it the plugin would be reported
        unregistered on top of the name-mismatch warning, and the autofix
        would append a duplicate entry for a directory already listed.

        A *local* entry contributes only its directory, never its name. The
        two are one registration, and crediting them independently lets a
        crossed pair — ``name: "b"`` against ``path: "./plugins/a"`` — cover
        both directories: A matches the path, B matches the name, and the
        fact that B is not installable at all goes unreported. Only remote
        entries (url, git-subdir, npm) register by name, because they name
        no directory in this repository for the path half to match.

        A malformed entry registers nothing at all. ``{"source": "local"}``
        with no ``path`` names no directory, and its ``name`` describes a
        plugin the catalog cannot install; crediting it would silence the
        unregistered-plugin report for a real directory of the same name.
        """
        names: Set[str] = set()
        dirs: Set[Path] = set()
        local_names: Set[str] = set()
        for node in context.lint_tree.find(CodexMarketplaceConfigNode):
            for _, entry in _entries(node.path):
                source = codex_local_source_path(entry.get("source"))
                if source is not None:
                    resolved = safe_resolve(context.root_path / source)
                    if resolved is not None:
                        dirs.add(resolved)
                    # The name is deliberately NOT credit — see above — but
                    # it is remembered: a directory whose name the catalog
                    # lists under a non-matching path is a different defect
                    # from one the catalog never mentions, and reporting
                    # the second message for the first sends the author
                    # grepping a catalog that already contains the name.
                    name = entry.get("name")
                    if isinstance(name, str):
                        local_names.add(name)
                    continue
                if not is_remote_source(entry.get("source")):
                    continue
                name = entry.get("name")
                if isinstance(name, str):
                    names.add(name)
        return names, dirs, local_names

    def _check_entries(
        self, context: RepositoryContext, marketplace_file: Path
    ) -> List[RuleViolation]:
        """Flag local entries whose plugin directory is missing or misnamed.

        Codex "skips that plugin entry instead of failing the whole
        marketplace" when it cannot resolve a source, so a dangling entry
        fails silently at install time — exactly what a linter should catch.

        Every violation here is ``fixable=False``: ``fix()`` only appends
        missing registrations, and ``violation()`` would otherwise default
        these to fixable because the rule declares ``autofix_confidence``.
        """
        violations: List[RuleViolation] = []

        for idx, entry in _entries(marketplace_file):
            source = codex_local_source_path(entry.get("source"))
            if source is None:
                continue  # remote source — nothing local to resolve
            plugin_dir = safe_resolve(context.root_path / source)
            if plugin_dir is None:
                continue  # unresolvable string — codex-marketplace-json-valid reports it
            if not (
                plugin_dir == context.root_path or plugin_dir.is_relative_to(context.root_path)
            ):
                continue  # escapes the repo — codex-marketplace-json-valid reports it

            if not safe_is_dir(plugin_dir):
                violations.append(
                    self.violation(
                        f"plugins[{idx}] source '{safe_display(source)}' does not exist",
                        file_path=marketplace_file,
                        fixable=False,
                    )
                )
                continue

            manifest = plugin_dir.joinpath(*context.CODEX_PLUGIN_MANIFEST)
            manifest_resolved = safe_resolve(manifest)
            if not safe_is_file(manifest) or (
                manifest_resolved is not None and not manifest_resolved.is_relative_to(plugin_dir)
            ):
                # This rule reads the manifest itself, so it needs its own
                # containment check — discovery's does not cover this path,
                # and a symlinked manifest would put an external file's name
                # into a violation message.
                violations.append(
                    self.violation(
                        f"plugins[{idx}] source '{safe_display(source)}' has no usable "
                        ".codex-plugin/plugin.json — Codex skips entries it "
                        "cannot resolve",
                        file_path=marketplace_file,
                        fixable=False,
                    )
                )
                continue

            entry_name = entry.get("name")
            manifest_name = codex_plugin_name(plugin_dir)
            if isinstance(entry_name, str) and entry_name != manifest_name:
                violations.append(
                    self.violation(
                        f"plugins[{idx}] name '{safe_display(entry_name)}' does not match "
                        f"the plugin manifest name '{safe_display(manifest_name)}'",
                        file_path=marketplace_file,
                        severity=Severity.WARNING,
                        fixable=False,
                    )
                )

        return violations

    def fix(
        self, context: RepositoryContext, violations: List[RuleViolation]
    ) -> List[AutofixResult]:
        results: List[AutofixResult] = []
        pending = [v for v in violations if "not registered" in v.message]
        if not pending:
            return results

        config_nodes = context.lint_tree.find(CodexMarketplaceConfigNode)
        if not config_nodes:
            return results
        marketplace_file = config_nodes[0].path

        original = _read_text(marketplace_file)
        data = _mutable_marketplace_data(original)
        if data is None:
            # Malformed document — reported by codex-marketplace-json-valid
            # and left for manual repair. check() marks these fixable=False.
            return results
        data.setdefault("plugins", [])

        # Re-derived rather than trusted from the violations: ``fixable`` is
        # a display flag, and the linter passes every visible violation here
        # regardless of it, so this is where the guards actually bite.
        registered_names, registered_dirs, local_names = self._registered(context)
        unregistered = [
            (d, n)
            for d, n in self._unregistered(context, registered_names, registered_dirs)
            # Name-listed entries get the WARNING path in check(), never a
            # catalog write — appending a second entry for a listed name
            # would create the duplicate the validity rule rejects.
            if n not in local_names
        ]
        registerable = self._registerable(context, unregistered, marketplace_file)

        # Violations are paired by rendering the message check() would have
        # produced rather than parsing a name back out of it — a name
        # containing an apostrophe would otherwise be truncated at the quote.
        fixed: List[RuleViolation] = []
        for name, plugin_dir in registerable.items():
            marker = self._unregistered_message(name, marketplace_file)
            violation = next((v for v in pending if v.message == marker), None)
            if violation is None:
                continue
            if any(p.get("name") == name for p in data["plugins"] if isinstance(p, dict)):
                continue
            source = _relative_source(plugin_dir, context)
            if source is None:  # pragma: no cover - _registerable already excluded these
                continue
            data["plugins"].append(
                {
                    "name": name,
                    "source": {"source": "local", "path": source},
                    "policy": dict(_NEW_ENTRY_POLICY),
                    "category": _NEW_ENTRY_CATEGORY,
                }
            )
            fixed.append(violation)

        if fixed:
            try:
                # Python's encoder otherwise emits NaN and Infinity, which
                # JavaScript accepts but the JSON standard and Codex manifests
                # do not. Parsing is strict above; allow_nan=False is the final
                # guard before returning content that the autofix will write.
                fixed_content = (
                    json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
                )
            except (ValueError, RecursionError):
                return results
            results.append(
                AutofixResult(
                    rule_id=self.rule_id,
                    file_path=marketplace_file,
                    confidence=AutofixConfidence.SUGGEST,
                    original_content=original,
                    # ensure_ascii=False above preserves non-ASCII text in
                    # untouched entries when the whole document is serialized.
                    fixed_content=fixed_content,
                    description=(f"Registered {len(fixed)} plugin(s) in {marketplace_file.name}"),
                    violations_fixed=fixed,
                )
            )

        return results


def _read_text(path: Path) -> str:
    """File text via the shared cached reader, which strips a UTF-8 BOM.

    Reading the manifest raw left a BOM in front of ``{``, so ``json.loads``
    failed and every registered plugin was reported unregistered.
    """
    return read_text(path) or ""


def _read_manifest(path: Path) -> Dict[str, Any]:
    data, error = read_json(path)
    return data if not error and isinstance(data, dict) else {}


def _entries(marketplace_file: Path) -> List[Tuple[int, dict]]:
    """``(index, entry)`` for each object in ``plugins``, or [] when malformed.

    The index is the entry's real position in the JSON array, not its
    position among the objects — a non-object entry earlier in the array
    would otherwise shift every reported ``plugins[N]`` out of line with the
    indices codex-marketplace-json-valid reports for the same file.
    """
    data, error = read_json(marketplace_file)
    if error or not isinstance(data, dict):
        return []
    entries = data.get("plugins")
    if not isinstance(entries, list):
        return []
    return [(idx, e) for idx, e in enumerate(entries) if isinstance(e, dict)]


def _relative_source(plugin_dir: Path, context: RepositoryContext) -> Optional[str]:
    """``./``-prefixed source for *plugin_dir*, or None if outside the root.

    Codex resolves ``source.path`` against the marketplace root — the
    repository root — not against ``.agents/plugins/``.
    """
    resolved = safe_resolve(plugin_dir)
    if resolved is None:
        return None
    try:
        relative = resolved.relative_to(context.root_path)
    except ValueError:
        return None
    return f"./{relative.as_posix()}" if relative.parts else "./"

"""Check literal repository-local Kiro references without reading runtime state."""

import re

from skillsaw.blocks.frontmatter import BodyContent
from skillsaw.blocks.kiro import KiroAgentConfigRole, KiroJsonAgentBlock, KiroSteeringBlock
from skillsaw.context import RepositoryType
from skillsaw.diagnostics import safe_display
from skillsaw.discovery.kiro import local_reference
from skillsaw.paths import safe_is_dir, safe_is_file
from skillsaw.rule import Rule, Severity
from skillsaw.utils import commented_item_line

# Kiro's own reference syntax inside AST-provided prose, not a Markdown parser.
_REFERENCE = re.compile(r"#\[\[(file|folder):([^\]\n]+)\]\]")
_LINE_SUFFIX = re.compile(r":\d+(?:-\d+)?$")


class KiroReferencesRule(Rule):
    """Report missing literal files; globs and global paths are unresolved here."""

    since = "0.21.1"
    default_enabled = False
    repo_types = frozenset({RepositoryType.KIRO})

    @property
    def rule_id(self):
        return "kiro-references"

    @property
    def description(self):
        return "Literal local Kiro prompt, resource, and steering references should exist"

    def default_severity(self):
        return Severity.WARNING

    def check(self, context):
        violations = []
        root = context.resolve_path(context.root_path)
        if root is None:
            return violations

        def check(path, base, source, line=None, folder=False):
            target = local_reference(
                path, base, root, resolve=context.resolve_path, is_excluded=context.is_path_excluded
            )
            if target is not None and not (safe_is_dir(target) if folder else safe_is_file(target)):
                violations.append(
                    self.violation(
                        f"Kiro reference '{safe_display(path)}' does not name an existing "
                        f"{'directory' if folder else 'file'}",
                        file_path=source,
                        line=line,
                    )
                )

        def workspace(path):
            return next(parent.parent for parent in path.parents if parent.name == ".kiro")

        for block in context.lint_tree.find(KiroAgentConfigRole):
            data = block.raw_data or {}
            # The documented Markdown body is the system prompt. Only the
            # JSON form's prompt URI is followed; no unverified precedence
            # between a Markdown body and a YAML prompt key is inferred.
            prompt = data.get("prompt")
            if (
                isinstance(block, KiroJsonAgentBlock)
                and isinstance(prompt, str)
                and prompt.startswith("file://")
            ):
                check(prompt[7:], block.path.parent, block.path)
            resources = data.get("resources")
            if isinstance(resources, list):
                for index, resource in enumerate(resources):
                    if isinstance(resource, str) and resource.startswith("file://"):
                        item_line = commented_item_line(resources, index)
                        check(
                            resource[7:],
                            workspace(block.path),
                            block.path,
                            item_line + 1 if item_line is not None else None,
                        )
        for steering in context.lint_tree.find(KiroSteeringBlock):
            for body in steering.find(BodyContent):
                for line, prose in body.markdown.prose_lines():
                    for match in _REFERENCE.finditer(prose):
                        kind, path = match.groups()
                        if kind == "file":
                            path = _LINE_SUFFIX.sub("", path)
                        check(
                            path,
                            workspace(steering.path),
                            steering.path,
                            line,
                            folder=kind == "folder",
                        )
        return violations

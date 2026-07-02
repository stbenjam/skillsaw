"""Example skillsaw plugin used by the integration tests.

Laid out exactly like a real published plugin: the distribution metadata in
the sibling ``.dist-info`` directory registers this module under the
``skillsaw.plugins`` entry point group, so adding the fixture directory to
``PYTHONPATH`` makes it discoverable just like a pip-installed package.
"""

from dataclasses import dataclass
from typing import List

from skillsaw import (
    AutofixConfidence,
    AutofixResult,
    RepositoryContext,
    Rule,
    RuleViolation,
    Severity,
)
from skillsaw.blocks import InstructionBlock, JsonConfigBlock
from skillsaw.plugins import PluginRepoType


class NoWipMarkersRule(Rule):
    """Instruction files should not ship work-in-progress markers."""

    autofix_confidence = AutofixConfidence.SAFE
    config_schema = {
        "markers": {
            "type": "list",
            "default": ["WIP:"],
            "description": "Markers that flag unfinished instructions",
        },
    }

    @property
    def rule_id(self) -> str:
        return "no-wip-markers"

    @property
    def description(self) -> str:
        return "Instruction files should not contain work-in-progress markers"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def _markers(self) -> List[str]:
        return self.config.get("markers", self.config_schema["markers"]["default"])

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        markers = self._markers()
        for block in context.lint_tree.find(InstructionBlock):
            content = block.read_body(strip_code_blocks=False)
            if content is None:
                continue
            for i, line in enumerate(content.splitlines(), start=1):
                if any(marker in line for marker in markers):
                    violations.append(
                        self.violation(
                            f"Work-in-progress marker: {line.strip()}",
                            block=block,
                            line=i,
                        )
                    )
        return violations

    def fix(self, context, violations) -> List[AutofixResult]:
        by_file = {}
        for v in violations:
            by_file.setdefault(v.file_path, []).append(v)

        results = []
        for path, file_violations in by_file.items():
            original = path.read_text(encoding="utf-8")
            lines = original.splitlines(keepends=True)
            remove = {v.file_line for v in file_violations if v.file_line}
            fixed = "".join(ln for i, ln in enumerate(lines, start=1) if i not in remove)
            if fixed != original:
                results.append(
                    AutofixResult(
                        rule_id=self.rule_id,
                        file_path=path,
                        confidence=AutofixConfidence.SAFE,
                        original_content=original,
                        fixed_content=fixed,
                        description="Removed work-in-progress marker lines",
                        violations_fixed=file_violations,
                    )
                )
        return results


@dataclass(eq=False)
class AcmeConfigBlock(JsonConfigBlock):
    """.acme/config.json — machine config, never linted as prose."""

    category: str = "acme-config"


class AcmeConfigVersionRule(Rule):
    """ACME config files must declare a version."""

    repo_types = {"acme"}  # plugin-contributed repo type (string entry)

    @property
    def rule_id(self) -> str:
        return "acme-config-version"

    @property
    def description(self) -> str:
        return "ACME config must declare a version field"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        for block in context.lint_tree.find(AcmeConfigBlock):
            if block.parse_error:
                violations.append(
                    self.violation(f"Invalid JSON: {block.parse_error}", file_path=block.path)
                )
            elif not isinstance(block.raw_data, dict) or "version" not in block.raw_data:
                violations.append(
                    self.violation("Missing required 'version' field", file_path=block.path)
                )
        return violations


def contribute_acme_config(context, root):
    """Attach .acme/config.json to the lint tree as a config block."""
    config_path = context.root_path / ".acme" / "config.json"
    if config_path.exists():
        return [AcmeConfigBlock(path=config_path)]
    return []


SKILLSAW_RULES = [NoWipMarkersRule, AcmeConfigVersionRule]

SKILLSAW_REPO_TYPES = [
    PluginRepoType(
        name="acme",
        description="Repository configured for the ACME assistant",
        detect=lambda root: (root / "ACME.md").exists() or (root / ".acme").is_dir(),
        content_paths=["ACME.md", ".acme/rules/*.md"],
    ),
]

SKILLSAW_TREE_CONTRIBUTORS = [contribute_acme_config]

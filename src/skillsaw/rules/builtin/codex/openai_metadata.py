"""Validate documented skill metadata and catalog-compatible plugin metadata."""

from __future__ import annotations

import re
from pathlib import Path
from typing import List

from skillsaw.blocks import OpenAIMetadataBlock
from skillsaw.context import RepositoryContext, SKILL_REPO_TYPES
from skillsaw.diagnostics import safe_display
from skillsaw.paths import is_absolute_path, safe_is_file, safe_resolve
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.rules.builtin.utils import (
    commented_item_line,
    commented_key_line,
    commented_root_line,
)

# The format OpenAI's bundled plugin validator enforces: six hex digits, no
# shorthand, no CSS keywords.
_BRAND_COLOR = re.compile(r"#[0-9a-fA-F]{6}")

_INTERFACE_STRINGS = (
    "display_name",
    "short_description",
    "icon_small",
    "icon_large",
    "brand_color",
    "default_prompt",
)


class CodexOpenAIMetadataRule(Rule):
    """Validate skill metadata and the observed plugin-root compatibility form."""

    repo_types = SKILL_REPO_TYPES
    since = "0.18.0"

    @property
    def rule_id(self) -> str:
        return "codex-openai-metadata"

    @property
    def description(self) -> str:
        return "Validate skill openai.yaml and catalog-compatible plugin metadata"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        for block in context.lint_tree.find(OpenAIMetadataBlock):
            if context.is_codex_installed_plugin(block.metadata_root):
                # Vendor-installed under .codex/plugins/: manifest quality
                # is the vendor's to fix — the same stand-down every other
                # manifest-quality rule applies there.
                continue
            if block.parse_error:
                violations.append(
                    self.violation(
                        # Parser diagnostics quote source text a malformed
                        # document controls — redact like any value echo.
                        f"Invalid YAML: {safe_display(block.parse_error)}",
                        file_path=block.path,
                        line=block.error_line,
                    )
                )
                continue
            data = block.raw_data
            if data is None:
                # An empty document ("", a lone comment, a bare "---")
                # declares nothing to validate — not an error.
                continue
            if not isinstance(data, dict):
                violations.append(
                    self.violation(
                        "openai.yaml must be a YAML mapping",
                        file_path=block.path,
                        line=commented_root_line(data),
                    )
                )
                continue
            self._validate_interface(block, data, violations)
            self._validate_policy(block, data, violations)
            self._validate_dependencies(block, data, violations)
        return violations

    def _validate_interface(
        self, block: OpenAIMetadataBlock, data: dict, violations: List[RuleViolation]
    ) -> None:
        interface = data.get("interface")
        if interface is None:
            return
        if not isinstance(interface, dict):
            violations.append(
                self.violation(
                    "'interface' must be a mapping",
                    file_path=block.path,
                    line=commented_key_line(data, "interface"),
                )
            )
            return
        for key in _INTERFACE_STRINGS:
            value = interface.get(key)
            if value is not None and not isinstance(value, str):
                violations.append(
                    self.violation(
                        f"'interface.{key}' must be a string",
                        file_path=block.path,
                        line=commented_key_line(interface, key),
                    )
                )
        brand_color = interface.get("brand_color")
        if isinstance(brand_color, str) and not _BRAND_COLOR.fullmatch(brand_color):
            # OpenAI's bundled plugin validator rejects anything but #RRGGBB,
            # so accepting a CSS keyword here would call metadata clean that
            # the platform refuses to load.
            violations.append(
                self.violation(
                    f"'interface.brand_color' must be a #RRGGBB hex color, got '{safe_display(brand_color)}'",
                    file_path=block.path,
                    line=commented_key_line(interface, "brand_color"),
                )
            )
        for key in ("icon_small", "icon_large"):
            value = interface.get(key)
            if isinstance(value, str):
                self._validate_icon(block, interface, key, value, violations)

    def _validate_icon(
        self,
        block: OpenAIMetadataBlock,
        interface: dict,
        key: str,
        value: str,
        violations: List[RuleViolation],
    ) -> None:
        line = commented_key_line(interface, key)
        if not value.strip():
            violations.append(
                self.violation(
                    f"'interface.{key}' is an empty path", file_path=block.path, line=line
                )
            )
            return
        if is_absolute_path(value):
            violations.append(
                self.violation(
                    f"'interface.{key}' must be relative to the metadata owner",
                    file_path=block.path,
                    line=line,
                )
            )
            return
        # Metadata may be authored on either operating system. Codex treats
        # both separators as path separators, so normalize before resolving;
        # otherwise ``..\outside.svg`` looks like an ordinary filename on
        # POSIX and bypasses the portable containment check.
        candidate = Path(value.replace("\\", "/"))
        resolved = safe_resolve(block.metadata_root / candidate)
        containment = safe_resolve(block.containment_root)
        if resolved is None or containment is None or not resolved.is_relative_to(containment):
            violations.append(
                self.violation(
                    f"'interface.{key}' path escapes the owning plugin or skill: '{safe_display(value)}'",
                    file_path=block.path,
                    line=line,
                )
            )
        elif not safe_is_file(resolved):
            violations.append(
                self.violation(
                    f"'interface.{key}' does not point to a bundled file: '{safe_display(value)}'",
                    file_path=block.path,
                    line=line,
                    severity=Severity.WARNING,
                )
            )

    def _validate_policy(
        self, block: OpenAIMetadataBlock, data: dict, violations: List[RuleViolation]
    ) -> None:
        policy = data.get("policy")
        if policy is None:
            return
        if not isinstance(policy, dict):
            violations.append(
                self.violation(
                    "'policy' must be a mapping",
                    file_path=block.path,
                    line=commented_key_line(data, "policy"),
                )
            )
            return
        value = policy.get("allow_implicit_invocation")
        if value is not None and not isinstance(value, bool):
            violations.append(
                self.violation(
                    "'policy.allow_implicit_invocation' must be true or false",
                    file_path=block.path,
                    line=commented_key_line(policy, "allow_implicit_invocation"),
                )
            )

    def _validate_dependencies(
        self, block: OpenAIMetadataBlock, data: dict, violations: List[RuleViolation]
    ) -> None:
        dependencies = data.get("dependencies")
        if dependencies is None:
            return
        if not isinstance(dependencies, dict):
            violations.append(
                self.violation(
                    "'dependencies' must be a mapping",
                    file_path=block.path,
                    line=commented_key_line(data, "dependencies"),
                )
            )
            return
        tools = dependencies.get("tools")
        if tools is None:
            return
        if not isinstance(tools, list):
            violations.append(
                self.violation(
                    "'dependencies.tools' must be an array",
                    file_path=block.path,
                    line=commented_key_line(dependencies, "tools"),
                )
            )
            return
        for index, tool in enumerate(tools):
            line = commented_item_line(tools, index)
            if not isinstance(tool, dict):
                violations.append(
                    self.violation(
                        f"'dependencies.tools[{index}]' must be a mapping",
                        file_path=block.path,
                        line=line,
                    )
                )
                continue
            for key in ("type", "value", "description", "transport", "url"):
                value = tool.get(key)
                if value is not None and not isinstance(value, str):
                    violations.append(
                        self.violation(
                            f"'dependencies.tools[{index}].{key}' must be a string",
                            file_path=block.path,
                            line=commented_key_line(tool, key) or line,
                        )
                    )

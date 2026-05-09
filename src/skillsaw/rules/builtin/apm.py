"""
Rules for validating APM (microsoft/apm) manifest files (apm.yml)
"""

import re
from typing import List, Optional, Dict, Any

import yaml

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.rules.builtin.utils import read_text

SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+")

SEMVER_RANGE_PATTERN = re.compile(
    r"^[\^~>=<*]?" r"(\d+|\*)" r"(\.\d+|\.\*)?" r"(\.\d+|\.\*)?" r"(\s*-\s*\d+\.\d+\.\d+)?$"
)

NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]{1,2}$")

VALID_TARGETS = {
    "vscode",
    "agents",
    "copilot",
    "claude",
    "cursor",
    "opencode",
    "codex",
    "gemini",
    "windsurf",
    "all",
    "minimal",
}

VALID_TYPES = {"instructions", "skill", "hybrid", "prompts"}

VALID_MCP_TRANSPORTS = {"stdio", "sse", "http", "streamable-http"}

VALID_MCP_PACKAGES = {"npm", "pypi", "oci"}

VALID_REGISTRIES = {"npm", "pypi", "github", "oci", "crates"}

COMMON_SPDX_IDS = {
    "MIT",
    "Apache-2.0",
    "GPL-2.0-only",
    "GPL-2.0-or-later",
    "GPL-3.0-only",
    "GPL-3.0-or-later",
    "LGPL-2.1-only",
    "LGPL-2.1-or-later",
    "LGPL-3.0-only",
    "LGPL-3.0-or-later",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "ISC",
    "MPL-2.0",
    "AGPL-3.0-only",
    "AGPL-3.0-or-later",
    "Unlicense",
    "0BSD",
    "CC0-1.0",
    "CC-BY-4.0",
    "CC-BY-SA-4.0",
    "Zlib",
    "BSL-1.0",
    "WTFPL",
    "Artistic-2.0",
    "ECL-2.0",
    "EPL-2.0",
    "EUPL-1.2",
    "PostgreSQL",
    "OFL-1.1",
    "NCSA",
}

WELL_KNOWN_PACKAGE_NAMES = {
    "express",
    "react",
    "vue",
    "angular",
    "next",
    "nuxt",
    "svelte",
    "lodash",
    "axios",
    "webpack",
    "babel",
    "eslint",
    "prettier",
    "jest",
    "mocha",
    "typescript",
    "flask",
    "django",
    "fastapi",
    "requests",
    "numpy",
    "pandas",
    "scipy",
    "tensorflow",
    "pytorch",
    "torch",
    "pytest",
    "black",
    "mypy",
    "ruff",
    "pip",
    "npm",
    "yarn",
    "pnpm",
}

DEPRECATED_FIELDS = {
    "targets": "target",
    "deps": "dependencies",
    "mcp_servers": "dependencies.mcp",
    "compile": "compilation",
    "build": "compilation",
    "pkg_type": "type",
    "package_type": "type",
}

EXPECTED_FIELD_TYPES = {
    "name": str,
    "version": str,
    "description": str,
    "author": str,
    "license": str,
    "type": str,
    "target": (str, list),
    "dependencies": dict,
    "compilation": dict,
    "main": str,
    "entry": str,
    "repository": str,
    "homepage": str,
    "keywords": list,
    "engines": dict,
}


def _find_apm_manifest(context: RepositoryContext):
    for name in ("apm.yml", "apm.yaml"):
        path = context.root_path / name
        if path.exists():
            return path
    return None


def _parse_apm_manifest(path):
    content = read_text(path)
    if content is None:
        return None, f"Failed to read {path.name}"
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as e:
        return None, f"Invalid YAML: {e}"
    if not isinstance(data, dict):
        return None, "Manifest must be a YAML mapping"
    return data, None


def _yaml_key_line(path, key: str) -> Optional[int]:
    content = read_text(path)
    if content is None:
        return None
    pattern = re.compile(rf"^{re.escape(key)}\s*:")
    for i, line in enumerate(content.splitlines(), 1):
        if pattern.match(line):
            return i
    return None


def _is_valid_semver_range(value: str) -> bool:
    if value in ("*", "latest"):
        return True
    value = value.strip()
    for part in value.split("||"):
        part = part.strip()
        if not part:
            return False
        if not SEMVER_RANGE_PATTERN.match(part):
            return False
    return True


class ApmManifestValidRule(Rule):
    """Validate apm.yml exists and has required fields"""

    repo_types = {RepositoryType.APM_PACKAGE}

    @property
    def rule_id(self) -> str:
        return "apm-manifest-valid"

    @property
    def description(self) -> str:
        return "apm.yml must exist with required name and version fields"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        manifest_path = _find_apm_manifest(context)

        if manifest_path is None:
            violations.append(
                self.violation("Missing apm.yml manifest", file_path=context.root_path)
            )
            return violations

        data, error = _parse_apm_manifest(manifest_path)
        if error:
            violations.append(self.violation(error, file_path=manifest_path))
            return violations

        # name (required)
        name = data.get("name")
        if not name:
            violations.append(
                self.violation("Missing required 'name' field", file_path=manifest_path)
            )
        elif not isinstance(name, str):
            violations.append(
                self.violation(
                    "'name' must be a string",
                    file_path=manifest_path,
                    line=_yaml_key_line(manifest_path, "name"),
                )
            )
        else:
            if len(name) < 3 or len(name) > 50:
                violations.append(
                    self.violation(
                        f"'name' must be 3-50 characters (got {len(name)})",
                        file_path=manifest_path,
                        line=_yaml_key_line(manifest_path, "name"),
                    )
                )
            if not NAME_PATTERN.match(name):
                violations.append(
                    self.violation(
                        "'name' must be lowercase alphanumeric with hyphens",
                        file_path=manifest_path,
                        line=_yaml_key_line(manifest_path, "name"),
                    )
                )

        # version (required, semver)
        version = data.get("version")
        if not version:
            violations.append(
                self.violation("Missing required 'version' field", file_path=manifest_path)
            )
        elif not isinstance(version, str):
            violations.append(
                self.violation(
                    "'version' must be a string",
                    file_path=manifest_path,
                    line=_yaml_key_line(manifest_path, "version"),
                )
            )
        elif not SEMVER_PATTERN.match(version):
            violations.append(
                self.violation(
                    f"'version' must be semver (MAJOR.MINOR.PATCH): {version!r}",
                    file_path=manifest_path,
                    line=_yaml_key_line(manifest_path, "version"),
                )
            )

        # description (warn if missing, error if >500 chars)
        desc = data.get("description")
        if desc is None:
            violations.append(
                self.violation(
                    "Missing 'description' field (recommended)",
                    file_path=manifest_path,
                    severity=Severity.WARNING,
                )
            )
        elif not isinstance(desc, str):
            violations.append(
                self.violation(
                    "'description' must be a string",
                    file_path=manifest_path,
                    line=_yaml_key_line(manifest_path, "description"),
                )
            )
        elif len(desc) > 500:
            violations.append(
                self.violation(
                    f"'description' exceeds 500 characters ({len(desc)})",
                    file_path=manifest_path,
                    line=_yaml_key_line(manifest_path, "description"),
                )
            )

        # author (optional, string)
        if "author" in data and not isinstance(data["author"], str):
            violations.append(
                self.violation(
                    "'author' must be a string",
                    file_path=manifest_path,
                    line=_yaml_key_line(manifest_path, "author"),
                )
            )

        # license (optional, validate SPDX if present)
        license_val = data.get("license")
        if license_val is not None:
            if not isinstance(license_val, str):
                violations.append(
                    self.violation(
                        "'license' must be a string (SPDX identifier)",
                        file_path=manifest_path,
                        line=_yaml_key_line(manifest_path, "license"),
                    )
                )
            elif license_val not in COMMON_SPDX_IDS:
                violations.append(
                    self.violation(
                        f"Unknown SPDX license identifier: {license_val!r}",
                        file_path=manifest_path,
                        line=_yaml_key_line(manifest_path, "license"),
                        severity=Severity.WARNING,
                    )
                )

        return violations


class ApmTargetValidRule(Rule):
    """Validate the target field in apm.yml"""

    repo_types = {RepositoryType.APM_PACKAGE}

    @property
    def rule_id(self) -> str:
        return "apm-target-valid"

    @property
    def description(self) -> str:
        return "apm.yml target must use valid target values"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        manifest_path = _find_apm_manifest(context)
        if manifest_path is None:
            return violations

        data, error = _parse_apm_manifest(manifest_path)
        if error or data is None:
            return violations

        target = data.get("target")
        if target is None:
            return violations

        line = _yaml_key_line(manifest_path, "target")

        if isinstance(target, str):
            if target not in VALID_TARGETS:
                violations.append(
                    self.violation(
                        f"Unknown target {target!r} (valid: {', '.join(sorted(VALID_TARGETS))})",
                        file_path=manifest_path,
                        line=line,
                    )
                )
        elif isinstance(target, list):
            for item in target:
                if not isinstance(item, str):
                    violations.append(
                        self.violation(
                            "Target list items must be strings",
                            file_path=manifest_path,
                            line=line,
                        )
                    )
                    break
                if item not in VALID_TARGETS:
                    violations.append(
                        self.violation(
                            f"Unknown target {item!r} (valid: {', '.join(sorted(VALID_TARGETS))})",
                            file_path=manifest_path,
                            line=line,
                        )
                    )
            if isinstance(target, list) and "all" in target and len(target) > 1:
                violations.append(
                    self.violation(
                        "'all' target cannot be combined with other targets",
                        file_path=manifest_path,
                        line=line,
                    )
                )
        else:
            violations.append(
                self.violation(
                    "'target' must be a string or list of strings",
                    file_path=manifest_path,
                    line=line,
                )
            )

        return violations


class ApmTypeValidRule(Rule):
    """Validate the type field in apm.yml"""

    repo_types = {RepositoryType.APM_PACKAGE}

    @property
    def rule_id(self) -> str:
        return "apm-type-valid"

    @property
    def description(self) -> str:
        return "apm.yml type must be a valid package type"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        manifest_path = _find_apm_manifest(context)
        if manifest_path is None:
            return violations

        data, error = _parse_apm_manifest(manifest_path)
        if error or data is None:
            return violations

        pkg_type = data.get("type")
        if pkg_type is None:
            return violations

        if not isinstance(pkg_type, str):
            violations.append(
                self.violation(
                    "'type' must be a string",
                    file_path=manifest_path,
                    line=_yaml_key_line(manifest_path, "type"),
                )
            )
        elif pkg_type not in VALID_TYPES:
            violations.append(
                self.violation(
                    f"Unknown type {pkg_type!r} (valid: {', '.join(sorted(VALID_TYPES))})",
                    file_path=manifest_path,
                    line=_yaml_key_line(manifest_path, "type"),
                )
            )

        return violations


class ApmDependenciesValidRule(Rule):
    """Validate dependencies in apm.yml"""

    repo_types = {RepositoryType.APM_PACKAGE}

    @property
    def rule_id(self) -> str:
        return "apm-dependencies-valid"

    @property
    def description(self) -> str:
        return "apm.yml dependencies must have valid apm and mcp entries"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        manifest_path = _find_apm_manifest(context)
        if manifest_path is None:
            return violations

        data, error = _parse_apm_manifest(manifest_path)
        if error or data is None:
            return violations

        deps = data.get("dependencies")
        if deps is None:
            return violations

        if not isinstance(deps, dict):
            violations.append(
                self.violation(
                    "'dependencies' must be a mapping",
                    file_path=manifest_path,
                    line=_yaml_key_line(manifest_path, "dependencies"),
                )
            )
            return violations

        apm_deps = deps.get("apm")
        if apm_deps is not None:
            violations.extend(self._check_apm_deps(apm_deps, manifest_path))

        mcp_deps = deps.get("mcp")
        if mcp_deps is not None:
            violations.extend(self._check_mcp_deps(mcp_deps, manifest_path))

        return violations

    def _check_apm_deps(self, apm_deps, manifest_path) -> List[RuleViolation]:
        violations = []
        if not isinstance(apm_deps, list):
            violations.append(
                self.violation(
                    "'dependencies.apm' must be a list",
                    file_path=manifest_path,
                )
            )
            return violations

        for i, dep in enumerate(apm_deps):
            if isinstance(dep, str):
                violations.extend(self._check_apm_dep_string(i, dep, manifest_path))
            elif isinstance(dep, dict):
                violations.extend(self._check_apm_dep_object(i, dep, manifest_path))
            else:
                violations.append(
                    self.violation(
                        f"dependencies.apm[{i}]: must be a string or object",
                        file_path=manifest_path,
                    )
                )

        return violations

    def _check_apm_dep_string(self, index: int, dep: str, manifest_path) -> List[RuleViolation]:
        violations = []
        prefix = f"dependencies.apm[{index}]"

        if "@" in dep:
            parts = dep.rsplit("@", 1)
            if len(parts) == 2:
                version_part = parts[1]
                if not _is_valid_semver_range(version_part):
                    violations.append(
                        self.violation(
                            f"{prefix}: invalid semver range {version_part!r}",
                            file_path=manifest_path,
                        )
                    )
                if version_part in ("*", "latest"):
                    violations.append(
                        self.violation(
                            f"{prefix}: avoid wildcard version {version_part!r}, pin to a specific range",
                            file_path=manifest_path,
                            severity=Severity.WARNING,
                        )
                    )

        return violations

    def _check_apm_dep_object(self, index: int, dep: dict, manifest_path) -> List[RuleViolation]:
        violations = []
        prefix = f"dependencies.apm[{index}]"

        if "git" not in dep and "path" not in dep:
            violations.append(
                self.violation(
                    f"{prefix}: object form requires 'git' or 'path'",
                    file_path=manifest_path,
                )
            )

        if "alias" in dep:
            alias = dep["alias"]
            if isinstance(alias, str) and not re.match(r"^[a-zA-Z0-9._-]+$", alias):
                violations.append(
                    self.violation(
                        f"{prefix}: 'alias' must match [a-zA-Z0-9._-]+",
                        file_path=manifest_path,
                    )
                )

        version = dep.get("version")
        if isinstance(version, str):
            if not _is_valid_semver_range(version):
                violations.append(
                    self.violation(
                        f"{prefix}: invalid semver range {version!r}",
                        file_path=manifest_path,
                    )
                )
            if version in ("*", "latest"):
                violations.append(
                    self.violation(
                        f"{prefix}: avoid wildcard version {version!r}, pin to a specific range",
                        file_path=manifest_path,
                        severity=Severity.WARNING,
                    )
                )

        registry = dep.get("registry")
        if isinstance(registry, str) and registry not in VALID_REGISTRIES:
            violations.append(
                self.violation(
                    f"{prefix}: unknown registry {registry!r} "
                    f"(valid: {', '.join(sorted(VALID_REGISTRIES))})",
                    file_path=manifest_path,
                )
            )

        return violations

    def _check_mcp_deps(self, mcp_deps, manifest_path) -> List[RuleViolation]:
        violations = []
        if not isinstance(mcp_deps, list):
            violations.append(
                self.violation(
                    "'dependencies.mcp' must be a list",
                    file_path=manifest_path,
                )
            )
            return violations

        for i, dep in enumerate(mcp_deps):
            if isinstance(dep, str):
                continue
            if isinstance(dep, dict):
                violations.extend(self._check_mcp_dep_dict(i, dep, manifest_path))
            else:
                violations.append(
                    self.violation(
                        f"dependencies.mcp[{i}]: must be a string or object",
                        file_path=manifest_path,
                    )
                )

        return violations

    def _check_mcp_dep_dict(
        self, index: int, dep: Dict[str, Any], manifest_path
    ) -> List[RuleViolation]:
        violations = []
        prefix = f"dependencies.mcp[{index}]"

        if "name" not in dep:
            violations.append(
                self.violation(
                    f"{prefix}: missing required 'name'",
                    file_path=manifest_path,
                )
            )

        transport = dep.get("transport")
        registry = dep.get("registry", True)
        is_self_defined = registry is False

        if transport is not None:
            if not isinstance(transport, str):
                violations.append(
                    self.violation(
                        f"{prefix}: 'transport' must be a string",
                        file_path=manifest_path,
                    )
                )
            elif transport not in VALID_MCP_TRANSPORTS:
                violations.append(
                    self.violation(
                        f"{prefix}: unknown transport {transport!r} "
                        f"(valid: {', '.join(sorted(VALID_MCP_TRANSPORTS))})",
                        file_path=manifest_path,
                    )
                )

        if is_self_defined:
            if transport is None:
                violations.append(
                    self.violation(
                        f"{prefix}: self-defined server (registry: false) requires 'transport'",
                        file_path=manifest_path,
                    )
                )
            elif isinstance(transport, str):
                if transport == "stdio" and "command" not in dep:
                    violations.append(
                        self.violation(
                            f"{prefix}: stdio transport requires 'command'",
                            file_path=manifest_path,
                        )
                    )
                elif transport in ("http", "sse", "streamable-http") and "url" not in dep:
                    violations.append(
                        self.violation(
                            f"{prefix}: {transport} transport requires 'url'",
                            file_path=manifest_path,
                        )
                    )

        if "package" in dep:
            pkg = dep["package"]
            if isinstance(pkg, str) and pkg not in VALID_MCP_PACKAGES:
                violations.append(
                    self.violation(
                        f"{prefix}: unknown package type {pkg!r} "
                        f"(valid: {', '.join(sorted(VALID_MCP_PACKAGES))})",
                        file_path=manifest_path,
                    )
                )

        if "env" in dep and not isinstance(dep["env"], dict):
            violations.append(
                self.violation(
                    f"{prefix}: 'env' must be a mapping",
                    file_path=manifest_path,
                )
            )

        if "headers" in dep and not isinstance(dep["headers"], dict):
            violations.append(
                self.violation(
                    f"{prefix}: 'headers' must be a mapping",
                    file_path=manifest_path,
                )
            )

        if "tools" in dep:
            tools = dep["tools"]
            if not isinstance(tools, list):
                violations.append(
                    self.violation(
                        f"{prefix}: 'tools' must be a list",
                        file_path=manifest_path,
                    )
                )
            elif not all(isinstance(t, str) for t in tools):
                violations.append(
                    self.violation(
                        f"{prefix}: 'tools' items must be strings",
                        file_path=manifest_path,
                    )
                )

        return violations


class ApmCompilationValidRule(Rule):
    """Validate compilation config in apm.yml"""

    repo_types = {RepositoryType.APM_PACKAGE}

    VALID_STRATEGIES = {"distributed", "single-file"}

    @property
    def rule_id(self) -> str:
        return "apm-compilation-valid"

    @property
    def description(self) -> str:
        return "apm.yml compilation config must use valid values"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        manifest_path = _find_apm_manifest(context)
        if manifest_path is None:
            return violations

        data, error = _parse_apm_manifest(manifest_path)
        if error or data is None:
            return violations

        compilation = data.get("compilation")
        if compilation is None:
            return violations

        if not isinstance(compilation, dict):
            violations.append(
                self.violation(
                    "'compilation' must be a mapping",
                    file_path=manifest_path,
                    line=_yaml_key_line(manifest_path, "compilation"),
                )
            )
            return violations

        strategy = compilation.get("strategy")
        if strategy is not None:
            if not isinstance(strategy, str):
                violations.append(
                    self.violation(
                        "'compilation.strategy' must be a string",
                        file_path=manifest_path,
                    )
                )
            elif strategy not in self.VALID_STRATEGIES:
                violations.append(
                    self.violation(
                        f"Unknown compilation strategy {strategy!r} "
                        f"(valid: {', '.join(sorted(self.VALID_STRATEGIES))})",
                        file_path=manifest_path,
                    )
                )

        output = compilation.get("output")
        if output is not None and not isinstance(output, str):
            violations.append(
                self.violation(
                    "'compilation.output' must be a string",
                    file_path=manifest_path,
                )
            )

        for bool_field in ("resolve_links", "source_attribution"):
            val = compilation.get(bool_field)
            if val is not None and not isinstance(val, bool):
                violations.append(
                    self.violation(
                        f"'compilation.{bool_field}' must be a boolean",
                        file_path=manifest_path,
                    )
                )

        exclude = compilation.get("exclude")
        if exclude is not None:
            if not isinstance(exclude, list):
                violations.append(
                    self.violation(
                        "'compilation.exclude' must be a list",
                        file_path=manifest_path,
                    )
                )
            elif not all(isinstance(e, str) for e in exclude):
                violations.append(
                    self.violation(
                        "'compilation.exclude' items must be strings",
                        file_path=manifest_path,
                    )
                )

        target = compilation.get("target")
        if target is not None:
            if not isinstance(target, str):
                violations.append(
                    self.violation(
                        "'compilation.target' must be a string",
                        file_path=manifest_path,
                    )
                )
            elif target not in VALID_TARGETS:
                violations.append(
                    self.violation(
                        f"Unknown compilation target {target!r} "
                        f"(valid: {', '.join(sorted(VALID_TARGETS))})",
                        file_path=manifest_path,
                    )
                )

        chatmode = compilation.get("chatmode")
        if chatmode is not None and not isinstance(chatmode, str):
            violations.append(
                self.violation(
                    "'compilation.chatmode' must be a string",
                    file_path=manifest_path,
                )
            )

        placement = compilation.get("placement")
        if placement is not None:
            if not isinstance(placement, dict):
                violations.append(
                    self.violation(
                        "'compilation.placement' must be a mapping",
                        file_path=manifest_path,
                    )
                )
            else:
                min_instr = placement.get("min_instructions_per_file")
                if min_instr is not None and not isinstance(min_instr, int):
                    violations.append(
                        self.violation(
                            "'compilation.placement.min_instructions_per_file' must be an integer",
                            file_path=manifest_path,
                        )
                    )

        return violations


# --- New rules ---


class ApmMcpTransportRule(Rule):
    """Validate MCP server transport configuration in apm.yml"""

    repo_types = {RepositoryType.APM_PACKAGE}

    @property
    def rule_id(self) -> str:
        return "apm-mcp-transport"

    @property
    def description(self) -> str:
        return "MCP server declarations must have valid transport configuration"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        manifest_path = _find_apm_manifest(context)
        if manifest_path is None:
            return violations

        data, error = _parse_apm_manifest(manifest_path)
        if error or data is None:
            return violations

        mcp_servers = data.get("mcp_servers") or data.get("mcp")
        if mcp_servers is None:
            deps = data.get("dependencies")
            if isinstance(deps, dict):
                mcp_servers = deps.get("mcp")

        if not isinstance(mcp_servers, list):
            return violations

        for i, server in enumerate(mcp_servers):
            if not isinstance(server, dict):
                continue

            prefix = f"mcp[{i}]"
            transport = server.get("transport")

            if transport is None:
                continue

            if not isinstance(transport, str):
                violations.append(
                    self.violation(
                        f"{prefix}: 'transport' must be a string",
                        file_path=manifest_path,
                    )
                )
                continue

            if transport not in VALID_MCP_TRANSPORTS:
                violations.append(
                    self.violation(
                        f"{prefix}: unknown transport {transport!r} "
                        f"(valid: {', '.join(sorted(VALID_MCP_TRANSPORTS))})",
                        file_path=manifest_path,
                    )
                )
                continue

            if transport == "stdio":
                if "command" not in server:
                    violations.append(
                        self.violation(
                            f"{prefix}: stdio transport requires 'command' field",
                            file_path=manifest_path,
                        )
                    )
            elif transport in ("sse", "streamable-http"):
                if "url" not in server:
                    violations.append(
                        self.violation(
                            f"{prefix}: {transport} transport requires 'url' field",
                            file_path=manifest_path,
                        )
                    )

            env = server.get("env")
            if isinstance(env, dict):
                for key, val in env.items():
                    if isinstance(val, str) and val.startswith("$") and val[1:]:
                        env_name = val[1:]
                        if not re.match(r"^[A-Z_][A-Z0-9_]*$", env_name):
                            violations.append(
                                self.violation(
                                    f"{prefix}: env var reference {val!r} has invalid format",
                                    file_path=manifest_path,
                                    severity=Severity.WARNING,
                                )
                            )

        return violations


class ApmLockfileConsistencyRule(Rule):
    """Check lockfile consistency with manifest"""

    repo_types = {RepositoryType.APM_PACKAGE}

    @property
    def rule_id(self) -> str:
        return "apm-lockfile-consistency"

    @property
    def description(self) -> str:
        return "apm.lock.yaml must be consistent with apm.yml dependencies"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        manifest_path = _find_apm_manifest(context)
        if manifest_path is None:
            return violations

        lock_path = context.root_path / "apm.lock.yaml"
        if not lock_path.exists():
            lock_path = context.root_path / "apm.lock.yml"
            if not lock_path.exists():
                return violations

        data, error = _parse_apm_manifest(manifest_path)
        if error or data is None:
            return violations

        lock_content = read_text(lock_path)
        if lock_content is None:
            return violations

        try:
            lock_data = yaml.safe_load(lock_content)
        except yaml.YAMLError:
            violations.append(
                self.violation(
                    "Invalid YAML in lockfile",
                    file_path=lock_path,
                )
            )
            return violations

        if not isinstance(lock_data, dict):
            violations.append(
                self.violation(
                    "Lockfile must be a YAML mapping",
                    file_path=lock_path,
                )
            )
            return violations

        deps = data.get("dependencies", {})
        if not isinstance(deps, dict):
            return violations

        manifest_dep_names = set()
        for dep_list in deps.values():
            if not isinstance(dep_list, list):
                continue
            for dep in dep_list:
                if isinstance(dep, str):
                    name = dep.split("@")[0].split("#")[0]
                    manifest_dep_names.add(name)
                elif isinstance(dep, dict):
                    name = dep.get("name") or dep.get("alias") or ""
                    if name:
                        manifest_dep_names.add(name)

        lock_packages = lock_data.get("packages", {})
        if not isinstance(lock_packages, dict):
            lock_packages = {}

        for dep_name in manifest_dep_names:
            if dep_name and dep_name not in lock_packages:
                violations.append(
                    self.violation(
                        f"Dependency {dep_name!r} in manifest but missing from lockfile",
                        file_path=lock_path,
                    )
                )

        for lock_name in lock_packages:
            if lock_name not in manifest_dep_names:
                violations.append(
                    self.violation(
                        f"Orphan entry {lock_name!r} in lockfile (not in manifest)",
                        file_path=lock_path,
                    )
                )

        return violations


class ApmReadmePresentRule(Rule):
    """Check that APM packages have a README"""

    repo_types = {RepositoryType.APM_PACKAGE}

    @property
    def rule_id(self) -> str:
        return "apm-readme-present"

    @property
    def description(self) -> str:
        return "APM packages should have a README.md"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        manifest_path = _find_apm_manifest(context)
        if manifest_path is None:
            return []

        for name in ("README.md", "readme.md", "Readme.md", "README"):
            if (context.root_path / name).exists():
                return []

        return [
            self.violation(
                "APM package should have a README.md",
                file_path=context.root_path,
            )
        ]


class ApmEntryPointRule(Rule):
    """Verify that entry point files exist"""

    repo_types = {RepositoryType.APM_PACKAGE}

    @property
    def rule_id(self) -> str:
        return "apm-entry-point"

    @property
    def description(self) -> str:
        return "Entry point file specified in main/entry must exist"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        manifest_path = _find_apm_manifest(context)
        if manifest_path is None:
            return violations

        data, error = _parse_apm_manifest(manifest_path)
        if error or data is None:
            return violations

        for field in ("main", "entry"):
            value = data.get(field)
            if isinstance(value, str):
                entry_path = context.root_path / value
                if not entry_path.exists():
                    violations.append(
                        self.violation(
                            f"Entry point '{field}: {value}' does not exist",
                            file_path=manifest_path,
                            line=_yaml_key_line(manifest_path, field),
                        )
                    )

        return violations


class ApmNameConflictRule(Rule):
    """Check for package name conflicts with well-known packages"""

    repo_types = {RepositoryType.APM_PACKAGE}

    @property
    def rule_id(self) -> str:
        return "apm-name-conflict"

    @property
    def description(self) -> str:
        return "Package name should not conflict with well-known npm/pypi packages"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        manifest_path = _find_apm_manifest(context)
        if manifest_path is None:
            return []

        data, error = _parse_apm_manifest(manifest_path)
        if error or data is None:
            return []

        name = data.get("name")
        if not isinstance(name, str):
            return []

        if name.lower() in WELL_KNOWN_PACKAGE_NAMES:
            return [
                self.violation(
                    f"Package name {name!r} conflicts with a well-known package",
                    file_path=manifest_path,
                    line=_yaml_key_line(manifest_path, "name"),
                )
            ]

        return []


class ApmFieldTypesRule(Rule):
    """Validate that YAML field types match the APM spec"""

    repo_types = {RepositoryType.APM_PACKAGE}

    @property
    def rule_id(self) -> str:
        return "apm-field-types"

    @property
    def description(self) -> str:
        return "YAML field value types must match the APM specification"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        manifest_path = _find_apm_manifest(context)
        if manifest_path is None:
            return violations

        data, error = _parse_apm_manifest(manifest_path)
        if error or data is None:
            return violations

        for field, expected in EXPECTED_FIELD_TYPES.items():
            value = data.get(field)
            if value is None:
                continue

            if isinstance(expected, tuple):
                if not isinstance(value, expected):
                    type_names = " or ".join(t.__name__ for t in expected)
                    violations.append(
                        self.violation(
                            f"'{field}' must be {type_names}, got {type(value).__name__}",
                            file_path=manifest_path,
                            line=_yaml_key_line(manifest_path, field),
                        )
                    )
            else:
                if not isinstance(value, expected):
                    if expected is str and isinstance(value, (int, float)):
                        violations.append(
                            self.violation(
                                f"'{field}' should be a string (quote the value)",
                                file_path=manifest_path,
                                line=_yaml_key_line(manifest_path, field),
                            )
                        )
                    else:
                        violations.append(
                            self.violation(
                                f"'{field}' must be {expected.__name__}, got {type(value).__name__}",
                                file_path=manifest_path,
                                line=_yaml_key_line(manifest_path, field),
                            )
                        )

        return violations

    def fix(self, context, violations):
        from skillsaw.rule import AutofixResult, AutofixConfidence

        results = []
        manifest_path = _find_apm_manifest(context)
        if manifest_path is None:
            return results

        content = read_text(manifest_path)
        if content is None:
            return results

        fixed = content
        fixed_violations = []

        for v in violations:
            if "should be a string (quote the value)" in v.message:
                field = v.message.split("'")[1]
                pattern = re.compile(rf"^({re.escape(field)}\s*:\s*)(\S+)", re.MULTILINE)
                match = pattern.search(fixed)
                if match:
                    val = match.group(2)
                    fixed = fixed[: match.start(2)] + f'"{val}"' + fixed[match.end(2) :]
                    fixed_violations.append(v)

        if fixed != content:
            results.append(
                AutofixResult(
                    rule_id=self.rule_id,
                    file_path=manifest_path,
                    confidence=AutofixConfidence.SAFE,
                    original_content=content,
                    fixed_content=fixed,
                    description="Quote numeric values that should be strings",
                    violations_fixed=fixed_violations,
                )
            )

        return results


class ApmDeprecatedFieldsRule(Rule):
    """Flag deprecated or renamed fields in apm.yml"""

    repo_types = {RepositoryType.APM_PACKAGE}

    @property
    def rule_id(self) -> str:
        return "apm-deprecated-fields"

    @property
    def description(self) -> str:
        return "Flag deprecated or renamed fields in apm.yml"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        manifest_path = _find_apm_manifest(context)
        if manifest_path is None:
            return violations

        data, error = _parse_apm_manifest(manifest_path)
        if error or data is None:
            return violations

        for old_field, new_field in DEPRECATED_FIELDS.items():
            if old_field in data:
                violations.append(
                    self.violation(
                        f"'{old_field}' is deprecated, use '{new_field}' instead",
                        file_path=manifest_path,
                        line=_yaml_key_line(manifest_path, old_field),
                    )
                )

        return violations

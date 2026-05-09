"""
Deep Claude Code rules: content quality, hook migration, skill quality,
MCP security, plugin size, rules overlap, agent delegation, and enhanced
context budget.
"""

import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import yaml

from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.rules.builtin.utils import frontmatter_key_line, read_json, read_text

_DOT_CLAUDE_TYPES = {RepositoryType.DOT_CLAUDE}

# ---------------------------------------------------------------------------
# Weak-language and tautology detectors (content intelligence)
# ---------------------------------------------------------------------------

_WEAK_PHRASES = [
    r"\btry to\b",
    r"\bmaybe\b",
    r"\bpossibly\b",
    r"\bif possible\b",
    r"\bwhen you can\b",
    r"\bit would be nice\b",
    r"\bideally\b",
    r"\bconsider\b",
    r"\byou might want to\b",
    r"\bperhaps\b",
    r"\bfeel free to\b",
]
_WEAK_RE = re.compile("|".join(_WEAK_PHRASES), re.IGNORECASE)

_TAUTOLOGIES = [
    r"\bdo what (?:you're|you are) told\b",
    r"\bfollow (?:the |these )?instructions\b",
    r"\bbe helpful\b",
    r"\bbe a good assistant\b",
    r"\byou are an? AI\b",
    r"\byou are Claude\b",
    r"\brespond helpfully\b",
]
_TAUTOLOGY_RE = re.compile("|".join(_TAUTOLOGIES), re.IGNORECASE)

# ---------------------------------------------------------------------------
# Hook-migration pattern detectors
# ---------------------------------------------------------------------------

_HOOK_PATTERNS: List[Tuple[re.Pattern, str, str]] = [
    (
        re.compile(
            r"\b(?:always|must|should)\s+(?:run|execute)\s+(?:the\s+)?(?:linter|lint|format(?:ter)?)\s+(?:after|before|when)",
            re.IGNORECASE,
        ),
        "PostToolUse",
        "Move to a PostToolUse hook for automatic linting/formatting",
    ),
    (
        re.compile(
            r"\b(?:format|lint)\s+(?:before|after)\s+(?:commit|saving|push)",
            re.IGNORECASE,
        ),
        "PreToolUse",
        "Move to a PreToolUse hook that triggers on commit/write operations",
    ),
    (
        re.compile(
            r"\bnever\s+(?:push|merge)\s+(?:to|into)\s+main\b",
            re.IGNORECASE,
        ),
        "Stop",
        "Enforce with a Stop hook instead of a prose instruction",
    ),
    (
        re.compile(
            r"\b(?:always|must)\s+run\s+tests?\s+(?:before|after)\b",
            re.IGNORECASE,
        ),
        "PreToolUse",
        "Move to a PreToolUse or PostToolUse hook for automatic test execution",
    ),
    (
        re.compile(
            r"\b(?:never|don't|do not)\s+(?:modify|edit|touch|change)\b",
            re.IGNORECASE,
        ),
        "PreToolUse",
        "Enforce file protection with a PreToolUse hook on Write/Edit",
    ),
]


def _estimate_tokens(text: str) -> int:
    return len(text) // 4


# ---------------------------------------------------------------------------
# 1. claude-md-quality
# ---------------------------------------------------------------------------


class ClaudeMdQualityRule(Rule):
    """Content quality analysis for CLAUDE.md files"""

    repo_types = _DOT_CLAUDE_TYPES

    config_schema = {
        "min_length": {
            "type": "int",
            "default": 50,
            "description": "Minimum character length for CLAUDE.md body content",
        },
        "max_weak_phrases": {
            "type": "int",
            "default": 5,
            "description": "Maximum number of weak/hedging phrases before warning",
        },
    }

    @property
    def rule_id(self) -> str:
        return "claude-md-quality"

    @property
    def description(self) -> str:
        return "CLAUDE.md should contain clear, actionable instructions without weak language or tautologies"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        claude_md = context.root_path / "CLAUDE.md"
        if not claude_md.exists():
            return violations

        content = read_text(claude_md)
        if content is None or not content.strip():
            return violations

        min_length = self.config.get("min_length", 50)
        max_weak = self.config.get("max_weak_phrases", 5)

        # Weak language detection
        weak_matches: List[Tuple[int, str]] = []
        for line_num, line in enumerate(content.splitlines(), 1):
            for m in _WEAK_RE.finditer(line):
                weak_matches.append((line_num, m.group()))

        if len(weak_matches) > max_weak:
            examples = ", ".join(f"'{p}'" for _, p in weak_matches[:3])
            violations.append(
                self.violation(
                    f"CLAUDE.md contains {len(weak_matches)} weak/hedging phrases "
                    f"(threshold: {max_weak}). Examples: {examples}. "
                    f"Use direct, imperative instructions instead",
                    file_path=claude_md,
                    line=weak_matches[0][0],
                )
            )

        # Tautology detection
        for line_num, line in enumerate(content.splitlines(), 1):
            for m in _TAUTOLOGY_RE.finditer(line):
                violations.append(
                    self.violation(
                        f"Tautological instruction '{m.group()}' — Claude already does this by default, remove it",
                        file_path=claude_md,
                        line=line_num,
                    )
                )

        # Content length (body only — strip frontmatter)
        body = content
        if content.startswith("---"):
            fm_end = content.find("---", 3)
            if fm_end != -1:
                body = content[fm_end + 3 :].strip()

        if len(body) < min_length:
            violations.append(
                self.violation(
                    f"CLAUDE.md body is only {len(body)} characters — "
                    f"add meaningful project-specific instructions",
                    file_path=claude_md,
                )
            )

        return violations


# ---------------------------------------------------------------------------
# 2. claude-md-hook-migration
# ---------------------------------------------------------------------------


class ClaudeMdHookMigrationRule(Rule):
    """Detect CLAUDE.md instructions that should be hooks"""

    repo_types = _DOT_CLAUDE_TYPES

    @property
    def rule_id(self) -> str:
        return "claude-md-hook-migration"

    @property
    def description(self) -> str:
        return "Detect instructions in CLAUDE.md that would be more reliable as hooks.json entries"

    def default_severity(self) -> Severity:
        return Severity.INFO

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        claude_md = context.root_path / "CLAUDE.md"
        if not claude_md.exists():
            return violations

        content = read_text(claude_md)
        if content is None:
            return violations

        for line_num, line in enumerate(content.splitlines(), 1):
            for pattern, event_type, suggestion in _HOOK_PATTERNS:
                if pattern.search(line):
                    violations.append(
                        self.violation(
                            f"This instruction looks like a {event_type} hook candidate. "
                            f"{suggestion}. "
                            f"See .claude/settings.json hooks format",
                            file_path=claude_md,
                            line=line_num,
                        )
                    )
                    break

        return violations


# ---------------------------------------------------------------------------
# 3. claude-skill-quality
# ---------------------------------------------------------------------------


class ClaudeSkillQualityRule(Rule):
    """Quality checks for SKILL.md files in .claude/skills/"""

    repo_types = _DOT_CLAUDE_TYPES

    config_schema = {
        "max_lines": {
            "type": "int",
            "default": 200,
            "description": "Maximum recommended lines for a single SKILL.md",
        },
    }

    @property
    def rule_id(self) -> str:
        return "claude-skill-quality"

    @property
    def description(self) -> str:
        return "SKILL.md files should have a clear purpose, examples, and reasonable size"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        max_lines = self.config.get("max_lines", 200)

        for plugin_path in context.plugins:
            skills_dir = plugin_path / "skills"
            if not skills_dir.is_dir():
                continue

            for skill_dir in sorted(skills_dir.iterdir()):
                if not skill_dir.is_dir():
                    continue
                skill_md = skill_dir / "SKILL.md"
                if not skill_md.exists():
                    continue

                content = read_text(skill_md)
                if content is None:
                    continue

                lines = content.splitlines()

                # Size check
                if len(lines) > max_lines:
                    violations.append(
                        self.violation(
                            f"SKILL.md is {len(lines)} lines (recommended max: {max_lines}). "
                            f"Consider splitting into smaller skills",
                            file_path=skill_md,
                        )
                    )

                body = content
                if content.startswith("---"):
                    fm_end = content.find("---", 3)
                    if fm_end != -1:
                        body = content[fm_end + 3 :]

                # Purpose statement — first non-empty paragraph should explain what the skill does
                body_stripped = body.strip()
                if body_stripped:
                    first_line = ""
                    for ln in body_stripped.splitlines():
                        ln = ln.strip()
                        if ln and not ln.startswith("#"):
                            first_line = ln
                            break
                    if len(first_line) < 10:
                        violations.append(
                            self.violation(
                                "SKILL.md lacks a clear purpose statement — "
                                "add a sentence explaining what this skill does",
                                file_path=skill_md,
                            )
                        )

        return violations


# ---------------------------------------------------------------------------
# 4. claude-mcp-security
# ---------------------------------------------------------------------------


class ClaudeMcpSecurityRule(Rule):
    """Security checks for MCP server configurations"""

    repo_types = _DOT_CLAUDE_TYPES

    @property
    def rule_id(self) -> str:
        return "claude-mcp-security"

    @property
    def description(self) -> str:
        return "Check MCP server configurations for security issues"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    _RISKY_COMMANDS = {
        "bash",
        "sh",
        "zsh",
        "cmd",
        "powershell",
        "pwsh",
        "node",
        "python",
        "python3",
    }

    _ENV_REF_RE = re.compile(r"\$\{?([A-Z_][A-Z0-9_]*)\}?")

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []

        mcp_files: List[Path] = []
        # Check .mcp.json at root
        root_mcp = context.root_path / ".mcp.json"
        if root_mcp.exists():
            mcp_files.append(root_mcp)

        # Check in plugin paths
        for plugin_path in context.plugins:
            p = plugin_path / ".mcp.json"
            if p.exists() and p not in mcp_files:
                mcp_files.append(p)

        for mcp_file in mcp_files:
            data, error = read_json(mcp_file)
            if error or not isinstance(data, dict):
                continue

            servers = data.get("mcpServers", {})
            if not isinstance(servers, dict):
                continue

            for name, config in servers.items():
                if not isinstance(config, dict):
                    continue

                server_type = config.get("type", "stdio")

                # Stdio servers with unrestricted shell commands
                if server_type == "stdio":
                    cmd = config.get("command", "")
                    if isinstance(cmd, str):
                        base_cmd = Path(cmd).name.lower() if cmd else ""
                        if base_cmd in self._RISKY_COMMANDS:
                            args = config.get("args", [])
                            has_eval = any(
                                isinstance(a, str) and a in ("-e", "-c", "--eval", "eval")
                                for a in (args if isinstance(args, list) else [])
                            )
                            if has_eval or not args:
                                violations.append(
                                    self.violation(
                                        f"MCP server '{name}' uses '{base_cmd}' with unrestricted "
                                        f"command execution — pin to a specific script or binary",
                                        file_path=mcp_file,
                                    )
                                )

                # SSE/HTTP without HTTPS
                if server_type in ("sse", "http"):
                    url = config.get("url", "")
                    if isinstance(url, str) and url.startswith("http://"):
                        if not any(
                            h in url for h in ("localhost", "127.0.0.1", "[::1]", "0.0.0.0")
                        ):
                            violations.append(
                                self.violation(
                                    f"MCP server '{name}' uses unencrypted HTTP for a non-local URL. "
                                    f"Use HTTPS to protect data in transit",
                                    file_path=mcp_file,
                                )
                            )

                # Environment variable references that are likely unset
                raw = str(config)
                env_refs = set(self._ENV_REF_RE.findall(raw))
                env_block = config.get("env", {})
                explicitly_set = set(env_block.keys()) if isinstance(env_block, dict) else set()
                # Standard env vars that are always available
                standard_env = {
                    "HOME",
                    "USER",
                    "PATH",
                    "SHELL",
                    "TERM",
                    "LANG",
                    "TMPDIR",
                    "PWD",
                    "CLAUDE_PLUGIN_ROOT",
                }
                missing = env_refs - explicitly_set - standard_env
                if missing:
                    violations.append(
                        self.violation(
                            f"MCP server '{name}' references environment variable(s) "
                            f"{', '.join(sorted(missing))} that are not set in 'env' block "
                            f"and are not standard variables",
                            file_path=mcp_file,
                            severity=Severity.INFO,
                        )
                    )

        return violations


# ---------------------------------------------------------------------------
# 5. claude-plugin-size
# ---------------------------------------------------------------------------


class ClaudePluginSizeRule(Rule):
    """Check total plugin content size against context budget"""

    repo_types = _DOT_CLAUDE_TYPES

    config_schema = {
        "warn_tokens": {
            "type": "int",
            "default": 8000,
            "description": "Token count at which to warn",
        },
        "error_tokens": {
            "type": "int",
            "default": 16000,
            "description": "Token count at which to error",
        },
    }

    @property
    def rule_id(self) -> str:
        return "claude-plugin-size"

    @property
    def description(self) -> str:
        return "Warn when total plugin content exceeds reasonable context budget limits"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        warn_tokens = self.config.get("warn_tokens", 8000)
        error_tokens = self.config.get("error_tokens", 16000)

        for plugin_path in context.plugins:
            total_tokens = 0
            breakdown: Dict[str, int] = {}

            # Scan all .md files in the plugin
            for category in ("commands", "skills", "agents", "rules"):
                cat_dir = plugin_path / category
                if not cat_dir.is_dir():
                    continue
                cat_tokens = 0
                for md_file in cat_dir.rglob("*.md"):
                    content = read_text(md_file)
                    if content:
                        cat_tokens += _estimate_tokens(content)
                if cat_tokens:
                    breakdown[category] = cat_tokens
                    total_tokens += cat_tokens

            # hooks.json
            hooks_json = plugin_path / "hooks" / "hooks.json"
            if hooks_json.exists():
                content = read_text(hooks_json)
                if content:
                    t = _estimate_tokens(content)
                    breakdown["hooks"] = t
                    total_tokens += t

            if total_tokens == 0:
                continue

            breakdown_str = ", ".join(f"{k}: ~{v:,}" for k, v in sorted(breakdown.items()))

            if total_tokens > error_tokens:
                violations.append(
                    self.violation(
                        f"Plugin content is ~{total_tokens:,} tokens (error threshold: "
                        f"{error_tokens:,}). Breakdown: {breakdown_str}",
                        file_path=plugin_path,
                        severity=Severity.ERROR,
                    )
                )
            elif total_tokens > warn_tokens:
                violations.append(
                    self.violation(
                        f"Plugin content is ~{total_tokens:,} tokens (warn threshold: "
                        f"{warn_tokens:,}). Breakdown: {breakdown_str}",
                        file_path=plugin_path,
                    )
                )

        return violations


# ---------------------------------------------------------------------------
# 6. claude-rules-overlap
# ---------------------------------------------------------------------------


class ClaudeRulesOverlapRule(Rule):
    """Check .claude/rules/ files for overlapping glob patterns"""

    repo_types = {RepositoryType.DOT_CLAUDE}

    @property
    def rule_id(self) -> str:
        return "claude-rules-overlap"

    @property
    def description(self) -> str:
        return "Check for overlapping path globs in .claude/rules/ frontmatter"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []

        claude_dir = context.root_path
        if context.root_path.name != ".claude":
            claude_dir = context.root_path / ".claude"
        rules_dir = claude_dir / "rules"
        if not rules_dir.is_dir():
            return violations

        # Collect all (file, glob) pairs
        file_globs: List[Tuple[Path, str, List[str]]] = []
        for rule_file in sorted(rules_dir.rglob("*.md")):
            content = read_text(rule_file)
            if content is None or not content.startswith("---"):
                continue
            match = re.match(r"^---\n(.*?)---", content, re.DOTALL)
            if not match:
                continue
            try:
                fm = yaml.safe_load(match.group(1))
            except yaml.YAMLError:
                continue
            if not isinstance(fm, dict):
                continue
            paths = fm.get("paths")
            if not isinstance(paths, list):
                continue
            str_paths = [p for p in paths if isinstance(p, str) and p.strip()]
            if str_paths:
                file_globs.append((rule_file, rule_file.name, str_paths))

        # Compare each pair
        for i in range(len(file_globs)):
            for j in range(i + 1, len(file_globs)):
                file_a, name_a, globs_a = file_globs[i]
                file_b, name_b, globs_b = file_globs[j]
                overlaps = self._find_overlaps(globs_a, globs_b)
                if overlaps:
                    violations.append(
                        self.violation(
                            f"Rules file '{name_a}' and '{name_b}' have overlapping "
                            f"path patterns: {', '.join(overlaps)}. "
                            f"Files matching both patterns will load both rule sets",
                            file_path=file_a,
                            line=frontmatter_key_line(file_a, "paths"),
                        )
                    )

        return violations

    @staticmethod
    def _find_overlaps(globs_a: List[str], globs_b: List[str]) -> List[str]:
        """Find glob patterns that could match the same files."""
        overlaps: List[str] = []
        for ga in globs_a:
            for gb in globs_b:
                if _globs_may_overlap(ga, gb):
                    overlaps.append(f"'{ga}' vs '{gb}'")
        return overlaps


def _globs_may_overlap(a: str, b: str) -> bool:
    """Heuristic: two globs may overlap if they share a common path prefix
    or one is a superset of the other (e.g., *.py vs src/**/*.py)."""
    # Exact match
    if a == b:
        return True

    # One contains ** (matches anything)
    if "**" in a or "**" in b:
        # Strip trailing wildcard portion and compare prefixes
        prefix_a = a.split("**")[0].rstrip("/")
        prefix_b = b.split("**")[0].rstrip("/")
        if not prefix_a or not prefix_b:
            return True
        return prefix_a.startswith(prefix_b) or prefix_b.startswith(prefix_a)

    # Same directory prefix with wildcard extensions
    parts_a = a.rsplit("/", 1)
    parts_b = b.rsplit("/", 1)
    dir_a = parts_a[0] if len(parts_a) > 1 else ""
    dir_b = parts_b[0] if len(parts_b) > 1 else ""
    file_a = parts_a[-1]
    file_b = parts_b[-1]

    if dir_a != dir_b:
        return False

    # Both are wildcards in the same directory
    if "*" in file_a and "*" in file_b:
        ext_a = file_a.replace("*", "")
        ext_b = file_b.replace("*", "")
        return ext_a == ext_b or ext_a.endswith(ext_b) or ext_b.endswith(ext_a)

    return False


# ---------------------------------------------------------------------------
# 7. claude-agent-delegation
# ---------------------------------------------------------------------------


class ClaudeAgentDelegationRule(Rule):
    """Quality checks for AGENTS.md agent definitions"""

    repo_types = _DOT_CLAUDE_TYPES

    config_schema = {
        "min_description_words": {
            "type": "int",
            "default": 5,
            "description": "Minimum word count for agent descriptions",
        },
    }

    @property
    def rule_id(self) -> str:
        return "claude-agent-delegation"

    @property
    def description(self) -> str:
        return "Check AGENTS.md for vague descriptions and missing tool/scope definitions"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        agents_md = context.root_path / "AGENTS.md"
        if not agents_md.exists():
            return violations

        content = read_text(agents_md)
        if content is None:
            return violations

        min_words = self.config.get("min_description_words", 5)
        agents = self._extract_agents(content)

        for agent_name, agent_info in agents.items():
            desc = agent_info.get("description", "")
            line = agent_info.get("line")

            # Vague description
            word_count = len(desc.split())
            if word_count < min_words:
                violations.append(
                    self.violation(
                        f"Agent '{agent_name}' has a vague description ({word_count} words). "
                        f"Add specific scope, responsibilities, and constraints",
                        file_path=agents_md,
                        line=line,
                    )
                )

            # No tool restrictions mentioned
            body = agent_info.get("body", "")
            tool_keywords = (
                "tool",
                "allowed",
                "permission",
                "access",
                "can use",
                "restricted",
                "scope",
            )
            if not any(kw in body.lower() for kw in tool_keywords):
                violations.append(
                    self.violation(
                        f"Agent '{agent_name}' has no tool access restrictions — "
                        f"define which tools or scopes this agent can use",
                        file_path=agents_md,
                        line=line,
                        severity=Severity.INFO,
                    )
                )

        return violations

    @staticmethod
    def _extract_agents(content: str) -> Dict[str, Dict]:
        """Extract agent definitions from AGENTS.md (heading-based sections).
        Only h2+ headings are treated as agent definitions; h1 is the document title."""
        agents: Dict[str, Dict] = {}
        heading_re = re.compile(r"^(#{2,3})\s+(.+)", re.MULTILINE)

        matches = list(heading_re.finditer(content))
        for i, m in enumerate(matches):
            level = len(m.group(1))
            name = m.group(2).strip()
            line_num = content[: m.start()].count("\n") + 1

            # Get body until next heading of same or higher level
            start = m.end()
            end = len(content)
            for j in range(i + 1, len(matches)):
                next_level = len(matches[j].group(1))
                if next_level <= level:
                    end = matches[j].start()
                    break

            body = content[start:end].strip()

            # First non-empty line after heading is the description
            desc_lines = []
            for ln in body.splitlines():
                ln = ln.strip()
                if not ln:
                    if desc_lines:
                        break
                    continue
                if ln.startswith("#"):
                    break
                desc_lines.append(ln)

            agents[name] = {
                "description": " ".join(desc_lines),
                "body": body,
                "line": line_num,
                "level": level,
            }

        return agents


# ---------------------------------------------------------------------------
# 8. claude-context-budget (enhanced — replaces existing context-budget)
# ---------------------------------------------------------------------------


class ClaudeContextBudgetRule(Rule):
    """Enhanced context budget: total across CLAUDE.md + skills + rules + hooks + subdirectory CLAUDE.md files"""

    repo_types = _DOT_CLAUDE_TYPES

    config_schema = {
        "warn_total_tokens": {
            "type": "int",
            "default": 8000,
            "description": "Total token count across all context files at which to warn",
        },
        "error_total_tokens": {
            "type": "int",
            "default": 16000,
            "description": "Total token count across all context files at which to error",
        },
    }

    @property
    def rule_id(self) -> str:
        return "claude-context-budget-total"

    @property
    def description(self) -> str:
        return "Check total context budget across all Claude Code configuration files"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        warn_total = self.config.get("warn_total_tokens", 8000)
        error_total = self.config.get("error_total_tokens", 16000)

        breakdown: Dict[str, int] = {}

        # Root CLAUDE.md
        claude_md = context.root_path / "CLAUDE.md"
        if claude_md.exists():
            content = read_text(claude_md)
            if content:
                breakdown["CLAUDE.md"] = _estimate_tokens(content)

        # Subdirectory CLAUDE.md files
        subdir_tokens = 0
        subdir_count = 0
        try:
            for sub_claude in context.root_path.rglob("CLAUDE.md"):
                if sub_claude == claude_md:
                    continue
                rel = sub_claude.relative_to(context.root_path)
                if any(part.startswith(".") for part in rel.parts[:-1]):
                    continue
                content = read_text(sub_claude)
                if content:
                    subdir_tokens += _estimate_tokens(content)
                    subdir_count += 1
        except OSError:
            pass
        if subdir_tokens:
            breakdown[f"Subdirectory CLAUDE.md ({subdir_count} files)"] = subdir_tokens

        # .claude/ directory content
        claude_dir = context.root_path
        if context.root_path.name != ".claude":
            claude_dir = context.root_path / ".claude"

        if claude_dir.is_dir():
            for category in ("skills", "rules", "commands", "agents"):
                cat_dir = claude_dir / category
                if not cat_dir.is_dir():
                    continue
                cat_tokens = 0
                for md_file in cat_dir.rglob("*.md"):
                    content = read_text(md_file)
                    if content:
                        cat_tokens += _estimate_tokens(content)
                if cat_tokens:
                    breakdown[f".claude/{category}"] = cat_tokens

            # Hooks
            hooks_json = claude_dir / "hooks" / "hooks.json"
            if not hooks_json.exists():
                # settings.json hooks are embedded
                settings_json = claude_dir / "settings.json"
                if settings_json.exists():
                    data, _ = read_json(settings_json)
                    if isinstance(data, dict) and "hooks" in data:
                        import json

                        hooks_str = json.dumps(data["hooks"])
                        breakdown[".claude/settings.json (hooks)"] = _estimate_tokens(hooks_str)

        total = sum(breakdown.values())
        if total == 0:
            return violations

        breakdown_str = ", ".join(f"{k}: ~{v:,}" for k, v in sorted(breakdown.items()))

        if total > error_total:
            violations.append(
                self.violation(
                    f"Total Claude Code context is ~{total:,} tokens (error threshold: "
                    f"{error_total:,}). Breakdown: {breakdown_str}",
                    file_path=claude_md if claude_md.exists() else context.root_path,
                    severity=Severity.ERROR,
                )
            )
        elif total > warn_total:
            violations.append(
                self.violation(
                    f"Total Claude Code context is ~{total:,} tokens (warn threshold: "
                    f"{warn_total:,}). Breakdown: {breakdown_str}",
                    file_path=claude_md if claude_md.exists() else context.root_path,
                )
            )

        return violations

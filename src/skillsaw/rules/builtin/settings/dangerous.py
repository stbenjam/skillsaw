"""
Rule: settings-dangerous

Flags settings keys that pose security risks when a repository ships
them: command-execution helpers and dangerous environment variables.
"""

import re
from typing import List, Set

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.content_analysis import SettingsBlock

# Keys that run arbitrary commands — a supply-chain risk in project settings
_COMMAND_EXEC_KEYS: Set[str] = {
    "apiKeyHelper",
    "awsAuthRefresh",
    "awsCredentialExport",
    "gcpAuthRefresh",
    "otelHeadersHelper",
}

# Environment variables that can hijack process behaviour
_DANGEROUS_ENV_VARS = re.compile(
    r"^(LD_PRELOAD|LD_LIBRARY_PATH|DYLD_INSERT_LIBRARIES|"
    r"NODE_OPTIONS|PYTHONSTARTUP|PYTHONPATH|PERL5OPT|PERL5LIB|RUBYOPT|RUBYLIB|"
    r"BASH_ENV|ENV|ZDOTDIR|"
    r"http_proxy|https_proxy|HTTP_PROXY|HTTPS_PROXY|"
    r"CURL_CA_BUNDLE|SSL_CERT_FILE|NODE_EXTRA_CA_CERTS|"
    r"GIT_SSH_COMMAND|GIT_PROXY_COMMAND)$"
)


class SettingsDangerousRule(Rule):
    """Flag security-sensitive settings in project settings."""

    since = "0.12.0"

    config_schema = {
        "allow_command_exec_keys": {
            "type": "list",
            "default": [],
            "description": "Command-execution keys to permit (e.g. apiKeyHelper)",
        },
        "allow_env_vars": {
            "type": "list",
            "default": [],
            "description": "Dangerous env var names to permit",
        },
    }

    @property
    def rule_id(self) -> str:
        return "settings-dangerous"

    @property
    def description(self) -> str:
        return (
            "Flags settings keys that execute arbitrary commands "
            "(apiKeyHelper, awsAuthRefresh, awsCredentialExport, gcpAuthRefresh, "
            "otelHeadersHelper) and dangerous env vars (LD_PRELOAD, NODE_OPTIONS, "
            "proxy settings, GIT_SSH_COMMAND, etc.)"
        )

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        allowed_exec = set(self.config.get("allow_command_exec_keys", []))
        allowed_env = set(self.config.get("allow_env_vars", []))

        for block in context.lint_tree.find(SettingsBlock):
            if block.parse_error or block.raw_data is None:
                continue
            data = block.raw_data
            path = block.path

            for key in _COMMAND_EXEC_KEYS:
                if key in data and key not in allowed_exec:
                    violations.append(
                        self.violation(
                            f"'{key}' executes arbitrary commands — " f"risky in project settings",
                            file_path=path,
                        )
                    )

            env = data.get("env")
            if isinstance(env, dict):
                for var_name in env:
                    if _DANGEROUS_ENV_VARS.match(var_name) and var_name not in allowed_env:
                        violations.append(
                            self.violation(
                                f"env.{var_name} can hijack process behaviour "
                                f"— risky in project settings",
                                file_path=path,
                            )
                        )

        return violations

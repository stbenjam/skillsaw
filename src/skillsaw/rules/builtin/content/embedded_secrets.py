"""Content embedded secrets rule"""

import re
from typing import List

from skillsaw.rule import AutofixConfidence, Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.content_analysis import (
    gather_all_content_blocks,
    FrontmatterField,
)


class ContentEmbeddedSecretsRule(Rule):
    """Detect potential secrets embedded in instruction files"""

    autofix_confidence = AutofixConfidence.LLM
    formats = None
    since = "0.7.0"

    @property
    def llm_fix_prompt(self):
        return (
            "You are fixing AI coding assistant instruction files that contain "
            "embedded secrets (API keys, tokens, passwords). Replace secrets "
            "with environment variable references.\n\n"
            "Rules:\n"
            "- Replace hardcoded secrets with environment variable references\n"
            "- Example: 'api_key = \"sk-abc123\"' → 'api_key = os.environ[\"API_KEY\"]'\n"
            "- For instruction prose, replace with placeholder like '$API_KEY'\n"
            "- Add a note about storing secrets in .env or environment variables\n"
            "- Do NOT remove the instruction, just redact the secret\n"
            "- Preserve markdown formatting"
        )

    _PATTERNS = [
        (re.compile(p), desc)
        for p, desc in [
            # OpenAI / Anthropic
            (r"\bsk-[a-zA-Z0-9]{20,}", "OpenAI/Anthropic API key"),
            (r"\bsk-ant-[a-zA-Z0-9\-_]{20,}", "Anthropic API key"),
            # GitHub
            (r"\bghp_[a-zA-Z0-9]{36,}", "GitHub personal access token"),
            (r"\bghs_[a-zA-Z0-9]{36,}", "GitHub server token"),
            (r"\bgho_[a-zA-Z0-9]{36,}", "GitHub OAuth token"),
            (r"\bghu_[a-zA-Z0-9]{36,}", "GitHub user token"),
            (r"\bghr_[a-zA-Z0-9]{36,}", "GitHub refresh token"),
            # GitLab
            (r"\bglpat-[a-zA-Z0-9\-_]{20,}", "GitLab personal access token"),
            # AWS
            (r"\bAKIA[0-9A-Z]{16}", "AWS access key ID"),
            (r"\bASIA[0-9A-Z]{16}", "AWS temporary access key ID"),
            # Slack
            (r"\bxoxb-[0-9]{10,}-[0-9a-zA-Z\-]+", "Slack bot token"),
            (r"\bxoxp-[0-9]{10,}-[0-9a-zA-Z\-]+", "Slack user token"),
            (r"\bxoxa-[0-9]{10,}-[0-9a-zA-Z\-]+", "Slack app token"),
            (r"\bxoxr-[0-9]{10,}-[0-9a-zA-Z\-]+", "Slack refresh token"),
            # Stripe
            (r"\bsk_live_[a-zA-Z0-9]{24,}", "Stripe secret key"),
            (r"\brk_live_[a-zA-Z0-9]{24,}", "Stripe restricted key"),
            # Google
            (r"\bAIza[0-9A-Za-z_\-]{35}", "Google API key"),
            # Twilio
            (r"\bSK[0-9a-fA-F]{32}", "Twilio API key"),
            # SendGrid
            (r"\bSG\.[a-zA-Z0-9_\-]{22}\.[a-zA-Z0-9_\-]{43}", "SendGrid API key"),
            # npm
            (r"\bnpm_[a-zA-Z0-9]{36}", "npm access token"),
            # PyPI
            (r"\bpypi-[a-zA-Z0-9]{16,}", "PyPI API token"),
            # JWT (base64.base64.base64)
            (r"\beyJ[a-zA-Z0-9_\-]*\.eyJ[a-zA-Z0-9_\-]*\.[a-zA-Z0-9_\-]+", "JSON Web Token"),
            # Private keys
            (r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----", "Private key"),
            # Generic patterns
            (r"(?i)\bpassword\s*[=:]\s*['\"][^'\"]{8,}['\"]", "Hardcoded password"),
            (r"(?i)\bapi[_-]?key\s*[=:]\s*['\"][^'\"]{16,}['\"]", "Hardcoded API key"),
            (r"(?i)\bsecret[_-]?key\s*[=:]\s*['\"][^'\"]{16,}['\"]", "Hardcoded secret key"),
            (r"(?i)\baccess[_-]?token\s*[=:]\s*['\"][^'\"]{16,}['\"]", "Hardcoded access token"),
        ]
    ]

    @property
    def rule_id(self) -> str:
        return "content-embedded-secrets"

    @property
    def description(self) -> str:
        return "Detect potential API keys, tokens, and passwords in instruction files"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        for cf in gather_all_content_blocks(context):
            body = cf.read_body(strip_code_blocks=False)
            if not body:
                continue
            for line_num, line in enumerate(body.splitlines(), 1):
                for pattern, desc in self._PATTERNS:
                    if pattern.search(line):
                        violations.append(
                            self.violation(
                                f"Potential secret detected: {desc}",
                                block=cf,
                                line=line_num,
                            )
                        )
                        break
        for fld in context.lint_tree.find(FrontmatterField):
            text = str(fld.value) if fld.value is not None else ""
            for pattern, desc in self._PATTERNS:
                if pattern.search(text):
                    violations.append(
                        self.violation(
                            f"Potential secret detected in frontmatter "
                            f"field '{fld.name}': {desc}",
                            file_path=fld.path,
                            line=fld.field_line,
                        )
                    )
                    break
        return violations

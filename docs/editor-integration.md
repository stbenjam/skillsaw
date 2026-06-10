# Editor Integration (LSP)

skillsaw ships a language server so lint violations appear as diagnostics
(squiggles) in CLAUDE.md, SKILL.md, hooks.json, and every other file skillsaw
lints — as you work, instead of only at commit or CI time.

## Installation

The language server is an optional extra built on
[pygls](https://github.com/openlsp/pygls):

```bash
pip install 'skillsaw[lsp]'
```

Verify it starts (it will wait silently for LSP input on stdin — press
Ctrl+C to exit):

```bash
skillsaw lsp
```

## What you get

- **Diagnostics on open and save** for the whole workspace. Cross-file rules
  (marketplace registration, plugins-doc-up-to-date) update diagnostics in
  every affected file, not just the one you saved.
- **Severity mapping**: skillsaw errors, warnings, and info map to editor
  error/warning/information severities.
- **Rule metadata**: each diagnostic carries its rule ID as the diagnostic
  code, with a clickable link to the rule documentation at
  [skillsaw.org/rules](https://skillsaw.org/rules/).
- **Config, suppressions, and baseline respected**: the server uses the same
  engine as `skillsaw lint`, so `.skillsaw.yaml`, inline
  `skillsaw-disable` comments, and `.skillsaw-baseline.json` all apply.
- **Quick fixes**: safe deterministic autofixes (the same ones `skillsaw fix`
  applies) are offered as quick-fix code actions on the diagnostic.

!!! note "Save-based linting"
    Diagnostics reflect file contents on disk. Unsaved buffer edits are not
    linted until you save — quick fixes are also withheld while a buffer has
    unsaved changes, so a stale fix can never clobber your edits.

## VS Code

There is no dedicated skillsaw extension yet. Use a generic LSP client such
as [Generic LSP Client](https://marketplace.visualstudio.com/items?itemName=llllvvuu.glspc)
(`llllvvuu.glspc`):

```jsonc
// settings.json
{
  "glspc.languageId": "markdown",
  "glspc.serverCommand": "skillsaw",
  "glspc.serverCommandArguments": ["lsp"]
}
```

Any extension that can launch an arbitrary LSP server over stdio works the
same way: command `skillsaw`, arguments `["lsp"]`, attached to markdown and
JSON/YAML documents.

## Cursor

Cursor supports VS Code extensions, so the same generic LSP client setup
works. Install the extension from Open VSX inside Cursor, then add the same
configuration to Cursor's `settings.json`:

```jsonc
{
  "glspc.languageId": "markdown",
  "glspc.serverCommand": "skillsaw",
  "glspc.serverCommandArguments": ["lsp"]
}
```

## Neovim

With Neovim 0.11+, configure the server with the built-in LSP API:

```lua
vim.lsp.config("skillsaw", {
  cmd = { "skillsaw", "lsp" },
  filetypes = { "markdown", "json", "yaml" },
  root_markers = {
    ".skillsaw.yaml",
    ".claude-plugin",
    "SKILL.md",
    ".git",
  },
})
vim.lsp.enable("skillsaw")
```

On older Neovim with `nvim-lspconfig`, register a custom server:

```lua
local configs = require("lspconfig.configs")
if not configs.skillsaw then
  configs.skillsaw = {
    default_config = {
      cmd = { "skillsaw", "lsp" },
      filetypes = { "markdown", "json", "yaml" },
      root_dir = require("lspconfig.util").root_pattern(
        ".skillsaw.yaml", ".claude-plugin", "SKILL.md", ".git"
      ),
    },
  }
end
require("lspconfig").skillsaw.setup({})
```

## Helix

Add the server to `~/.config/helix/languages.toml`:

```toml
[language-server.skillsaw]
command = "skillsaw"
args = ["lsp"]

[[language]]
name = "markdown"
language-servers = ["skillsaw"]
```

## Zed

Zed loads language servers through extensions; until a skillsaw extension
exists, you can point Zed at the server for markdown via a local extension or
use save-based CLI linting in a task. Watch
[issue #280](https://github.com/stbenjam/skillsaw/issues/280) for progress on
packaged editor extensions.

## Troubleshooting

- **No diagnostics appear**: the server lints the workspace root your editor
  opened. Make sure you opened the repository root (where `.skillsaw.yaml` or
  the plugin/skill lives), not a subdirectory or a single file.
- **`skillsaw lsp` exits immediately with an error**: install the extra —
  `pip install 'skillsaw[lsp]'`. The error message says exactly this.
- **Diagnostics seem stale**: linting is save-based. Save the file; the
  server re-lints the workspace on every save and on watched-file changes
  (git checkouts, external edits) in editors that support file watching.
- **Server logs**: the server logs to stderr, which most editors surface in
  their LSP/output panel.

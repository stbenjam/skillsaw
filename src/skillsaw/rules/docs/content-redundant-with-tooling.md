## Why

Instructions that restate what `.editorconfig`, ESLint, Prettier, or
`tsconfig.json` already enforce waste context budget without changing
behavior — the tooling runs regardless of what the instruction file
says. Worse, if the instruction and the config diverge, the model
faces a contradiction it cannot resolve.

## Examples

**Bad (when .editorconfig already sets indent_size = 2):**

```markdown
Use 2-space indentation in all files.
```

**Good:**

```markdown
Indentation is enforced by .editorconfig — do not override it.
```

Or simply remove the line entirely.

## How to fix

Delete the redundant instruction. If you want the model to be aware
of the setting, reference the config file instead of restating its
contents. A coding agent can remove flagged lines automatically.
